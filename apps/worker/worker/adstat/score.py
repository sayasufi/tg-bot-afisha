"""Скоринг каналов «брать / осторожно / мимо» по pro-маркерам закупки.

Мёрджит последние метрики по каналу из ВСЕХ источников (telethon: охват/ER; telega: цена/CPM;
telemetr: фрод-флаги) и считает скор + причину. Правила — как у профи:
  - фрод-флаг (scam/накрутка/санкции) → сразу «мимо»;
  - охват < ~12-15% подписчиков → мёртвая/купленная аудитория → «мимо»;
  - ER > 60% → боты → «мимо»;
  - бонусы за хороший охват/подписчики, нормальный ER и низкий CPM.
"""
from __future__ import annotations

from sqlalchemy import select

from core.db.models.adstat import AdChannel, AdSnapshot
from core.db.session import SessionLocal

_FIELDS = ["subscribers", "avg_reach", "er", "err", "cpm", "post_price", "rating",
           "is_scam", "is_boosting", "sanctioned", "quality_score", "mentions"]


def _merge(snaps: list[dict]) -> dict:
    """Из снимков (свежие первыми) берём первое не-None по каждому полю."""
    m: dict = {}
    for key in _FIELDS:
        for s in snaps:
            if s.get(key) is not None:
                m[key] = s[key]
                break
    return m


def score_channel(m: dict) -> tuple[int, str, str]:
    subs, reach = m.get("subscribers"), m.get("avg_reach")
    er = m.get("er") if m.get("er") is not None else m.get("err")
    cpm = m.get("cpm")
    fraud = m.get("is_scam") or m.get("is_boosting") or m.get("sanctioned")
    if fraud:
        return 0, "мимо", "фрод-флаг (накрутка/scam/санкции)"
    rr = (reach / subs) if (subs and reach) else None
    if rr is not None and rr < 0.12:
        return 10, "мимо", f"охват {rr * 100:.0f}% от подписчиков — мёртвая/купленная аудитория"
    if er and er > 60:
        return 15, "мимо", f"ER {er}% — признак ботов"

    s = 45.0
    why = []
    if rr is not None:
        s += min(25, rr * 60)
        if rr >= 0.3:
            why.append(f"охват {rr * 100:.0f}%")
    if er and 2 <= er <= 35:
        s += 12
        why.append(f"ER {er}%")
    if cpm:
        if cpm <= 500:
            s += 18; why.append(f"CPM {cpm:.0f}₽ дёшево")
        elif cpm <= 1200:
            s += 8; why.append(f"CPM {cpm:.0f}₽ норма")
        elif cpm > 2500:
            s -= 18; why.append(f"CPM {cpm:.0f}₽ дорого")
    s = max(0, min(100, round(s)))
    verdict = "брать" if s >= 68 else ("осторожно" if s >= 48 else "мимо")
    return s, verdict, ", ".join(why) or "мало данных"


def rank(min_reach: int = 2000, limit: int = 100) -> list[dict]:
    out: list[dict] = []
    with SessionLocal() as db:
        channels = db.execute(select(AdChannel)).scalars().all()
        for ch in channels:
            snaps = db.execute(
                select(AdSnapshot).where(AdSnapshot.channel_id == ch.channel_id)
                .order_by(AdSnapshot.captured_at.desc()).limit(10)
            ).scalars().all()
            m = _merge([{f: getattr(s, f, None) for f in _FIELDS} for s in snaps])
            if not m.get("avg_reach") or m["avg_reach"] < min_reach:
                continue
            sc, verdict, why = score_channel(m)
            out.append({
                "username": ch.username, "title": ch.title, "score": sc, "verdict": verdict,
                "reason": why, "subscribers": m.get("subscribers"), "reach": m.get("avg_reach"),
                "er": m.get("er") or m.get("err"), "cpm": m.get("cpm"), "price": m.get("post_price"),
            })
    out.sort(key=lambda x: -x["score"])
    return out[:limit]
