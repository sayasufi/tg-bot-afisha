"""Кастомные рассылки (кампании) — paced sender + dispatcher. Живёт в воркере, реальная отправка
ТОЛЬКО через Prefect-флоу dispatch_broadcasts (не синхронно из API).

Безопасность:
- Идемпотентность = ledger ref.broadcast_recipients (PK campaign+user): INSERT ON CONFLICT DO NOTHING;
  0 строк → уже отправлено → пропуск. Crash-stranded 'pending' (>15м) reaper помечает 'permanent'
  (НЕ переотправляем — редкая потеря лучше дабл-спама).
- Опт-аут notify_broadcasts уважается ВСЕГДА (не bypass-ится) для боевой отправки.
- Тест: only_user_id → жёсткий [:1] на admin_test_user_id, ledger НЕ пишется, статус кампании не трогается.
- Темп: PACE/classify/retry_after переиспользуются из tg_send (НЕ свой тугой цикл).
"""
import asyncio
import json

import httpx
from sqlalchemy import text

from apps.worker.tasks.tg_send import PACE, classify, retry_after
from core.config.settings import get_settings
from core.db.session import WorkerAsyncSessionLocal
from core.infra.http_safety import is_public_http_url


def audience_filter(audience: dict | None) -> tuple[str, dict]:
    """WHERE-фрагмент по аудитории (для ref.users u) + params. ВСЕГДА фильтрует notify_broadcasts (опт-аут)."""
    a = audience or {}
    kind = a.get("kind", "opted_in")
    conds = ["u.notify_broadcasts IS TRUE"]
    params: dict = {}
    if kind == "opted_in":
        conds.append("u.notify_digest IS TRUE")
    elif kind == "city":
        cities = [c for c in (a.get("cities") or []) if isinstance(c, str)]
        conds.append("u.city_slug = ANY(:cities)")
        params["cities"] = cities or ["__none__"]
    elif kind == "active_since":
        conds.append("u.last_active_at > now() - make_interval(days => :days)")
        params["days"] = int(a.get("since_days") or 7)
    # kind == 'all' → только опт-аут-фильтр
    return " AND ".join(conds), params


async def audience_count(db, audience: dict | None) -> tuple[int, dict]:
    """Dry-run: точное число получателей + разбивка по городам. ТОЧНО тот же resolver, что и отправка."""
    where, params = audience_filter(audience)
    total = (await db.execute(text(f"SELECT count(*) FROM ref.users u WHERE {where}"), params)).scalar()
    rows = (await db.execute(text(
        f"SELECT COALESCE(u.city_slug, '—') AS c, count(*) AS n FROM ref.users u WHERE {where} GROUP BY 1 ORDER BY 2 DESC"
    ), params)).all()
    return int(total or 0), {r[0]: int(r[1]) for r in rows}


async def _resolve_audience(db, audience: dict | None, only_user_id: int | None) -> list[int]:
    if only_user_id is not None:
        return [only_user_id]
    where, params = audience_filter(audience)
    return list((await db.execute(text(f"SELECT u.telegram_user_id FROM ref.users u WHERE {where}"), params)).scalars().all())


def _markup(label: str | None, url: str | None):
    if label and url:
        return {"inline_keyboard": [[{"text": label, "url": url}]]}
    return None


async def _fetch_image(url: str | None) -> bytes | None:
    if not url or not is_public_http_url(url):
        return None
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(url, follow_redirects=False, headers={"User-Agent": "okrest-broadcast/1.0"})
            r.raise_for_status()
            return r.content
    except Exception:
        return None


async def _send_one(client, base, user_id, photo, body_html, markup) -> str:
    """Одна отправка (фото+подпись с фолбэком на текст), 1 retry на 429/5xx. 'ok'|'permanent'|'retry'."""
    for attempt in range(2):
        try:
            if photo:
                resp = await client.post(
                    f"{base}/sendPhoto",
                    data={"chat_id": str(user_id), "caption": body_html, "parse_mode": "HTML",
                          **({"reply_markup": json.dumps(markup)} if markup else {})},
                    files={"photo": ("b.jpg", photo, "image/jpeg")},
                )
                data = resp.json()
                if classify(data) == "permanent":  # фото отвергнуто → текст всё равно уходит
                    resp = await client.post(f"{base}/sendMessage", json={
                        "chat_id": user_id, "parse_mode": "HTML", "text": body_html,
                        "disable_web_page_preview": True, **({"reply_markup": markup} if markup else {})})
                    data = resp.json()
            else:
                resp = await client.post(f"{base}/sendMessage", json={
                    "chat_id": user_id, "parse_mode": "HTML", "text": body_html,
                    "disable_web_page_preview": True, **({"reply_markup": markup} if markup else {})})
                data = resp.json()
        except Exception:
            return "retry"
        verdict = classify(data)
        if verdict != "retry":
            return verdict
        if attempt == 0:
            await asyncio.sleep(retry_after(data))
    return "retry"


async def send_campaign_impl(campaign_id: str, only_user_id: int | None = None) -> dict:
    """Отправка кампании. only_user_id → ТЕСТ строго одному (ledger не пишется, статус не трогается)."""
    token = get_settings().telegram_bot_token
    if not token:
        return {"sent": 0, "failed": 0, "skipped": 0}
    base = f"https://api.telegram.org/bot{token}"
    async with WorkerAsyncSessionLocal() as db:
        c = (await db.execute(text(
            "SELECT body, image_url, button_label, button_url, audience, status, test_sent_at, confirmed_at "
            "FROM ref.broadcast_campaigns WHERE id = CAST(:id AS uuid)"
        ), {"id": campaign_id})).mappings().first()
        if c is None:
            return {"sent": 0, "failed": 0, "skipped": 0}
        if only_user_id is None:
            if c["status"] not in ("scheduled", "sending"):
                return {"sent": 0, "failed": 0, "skipped": 0}
            if c["test_sent_at"] is None or c["confirmed_at"] is None:
                raise RuntimeError("campaign not gated: test+confirm required")
            await db.execute(text(
                "UPDATE ref.broadcast_campaigns SET status='sending', "
                "dispatch_started_at=COALESCE(dispatch_started_at, now()), updated_at=now() WHERE id=CAST(:id AS uuid)"
            ), {"id": campaign_id})
            await db.commit()
        audience = c["audience"] if isinstance(c["audience"], dict) else json.loads(c["audience"] or "{}")
        user_ids = await _resolve_audience(db, audience, only_user_id)
        if only_user_id is not None:
            user_ids = [u for u in user_ids if u == only_user_id][:1]  # HARD test guard
        photo = await _fetch_image(c["image_url"])
        markup = _markup(c["button_label"], c["button_url"])
        sent = failed = 0
        async with httpx.AsyncClient(timeout=20) as client:
            for uid in user_ids:
                if only_user_id is None:
                    claimed = (await db.execute(text(
                        "INSERT INTO ref.broadcast_recipients (campaign_id, telegram_user_id, status) "
                        "VALUES (CAST(:cid AS uuid), :uid, 'pending') ON CONFLICT DO NOTHING RETURNING telegram_user_id"
                    ), {"cid": campaign_id, "uid": uid})).first()
                    await db.commit()
                    if claimed is None:
                        continue  # уже в ledger → не задваиваем
                res = await _send_one(client, base, uid, photo, c["body"], markup)
                if only_user_id is None:
                    # 'retry' оставляем 'pending' (reaper потом → 'permanent', не переотправляем).
                    final = res if res in ("ok", "permanent") else "pending"
                    await db.execute(text(
                        "UPDATE ref.broadcast_recipients SET status=:s, sent_at=now() "
                        "WHERE campaign_id=CAST(:cid AS uuid) AND telegram_user_id=:uid"
                    ), {"s": final, "cid": campaign_id, "uid": uid})
                    await db.commit()
                sent += res == "ok"
                failed += res != "ok"
                await asyncio.sleep(PACE)
        if only_user_id is None:
            await db.execute(text(
                "UPDATE ref.broadcast_campaigns SET status='sent', sent_count=sent_count+:s, "
                "failed_count=failed_count+:f, updated_at=now() WHERE id=CAST(:id AS uuid)"
            ), {"s": sent, "f": failed, "id": campaign_id})
            await db.commit()
    return {"sent": sent, "failed": failed, "skipped": 0}


async def _dispatch_due_impl() -> dict:
    """Один проход: reaper stale-claims + запуск ДОЗРЕВШИХ кампаний (now / at_utc). Ledger = идемпотентность."""
    async with WorkerAsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE ref.broadcast_recipients SET status='permanent' "
            "WHERE status='pending' AND sent_at < now() - interval '15 minutes'"
        ))
        await db.commit()
        due = list((await db.execute(text(
            "SELECT id::text FROM ref.broadcast_campaigns WHERE status IN ('scheduled','sending') "
            "AND (schedule_kind='now' OR (schedule_kind='at_utc' AND scheduled_at <= now())) "
            "ORDER BY created_at LIMIT 5"
        ))).scalars().all())
    ran = []
    for cid in due:
        try:
            ran.append({"campaign": cid, **(await send_campaign_impl(cid))})
        except Exception as exc:
            ran.append({"campaign": cid, "error": repr(exc)})
    return {"dispatched": ran}
