"""Скоринг каналов «брать / осторожно / мимо» по pro-маркерам закупки рекламы (посев).

Модель основана на консенсусе индустрии (eLama / Bidfox / TGStat / Telemetr — см. ресёрч):
  ГЛАВНОЕ — охват от подписчиков (ERR = охват/подписчики): живость аудитории.
    норма 15–45%; <10% → мёртвая/купленная аудитория («мимо»); >60% → флаг накрутки просмотров.
  ЦЕНА — CPM (₽ за 1000 просмотров): медиана натив-посева ~150–180₽. Норма ~до 350₽; дорого >600–1000₽.
    Слишком дёшево (<80₽) — ТОЖЕ подозрительно (плохая аудитория), не «чем дешевле тем лучше».
  АВТОРИТЕТ — упоминания/цитируемость другими каналами → бонус.
  ФРОД — is_scam / накрутка (boosting) / санкции → сразу «мимо».

Мёрджит свежие метрики канала из ВСЕХ источников (telethon: охват; telega: цена; telemetr: фрод/упоминания).
CPM считаем сами из цены и охвата, если не сохранён. Реакционный ER в данных неоднозначен по источникам
(ERR vs реакции), поэтому охват/подписчики считаем САМИ и на ambiguous-поле не опираемся.
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
    subs = m.get("subscribers")
    reach = m.get("avg_reach")
    cpm = m.get("cpm")
    price = m.get("post_price")
    mentions = m.get("mentions")
    fraud = m.get("is_scam") or m.get("is_boosting") or m.get("sanctioned")

    # CPM (₽ за 1000 просмотров) — считаем сами, если источник не дал.
    if cpm is None and price and reach:
        cpm = price / reach * 1000.0

    # --- ЖЁСТКИЕ ОТСЕВЫ (анти-фрод) ---
    if fraud:
        return 0, "мимо", "фрод-флаг (scam / накрутка / санкции)"
    rr = (reach / subs) if (subs and reach) else None  # ERR = охват/подписчики (главный признак живости)
    if rr is not None and rr < 0.10:
        return 8, "мимо", f"охват {rr * 100:.0f}% подписчиков (<10%) — мёртвая/купленная аудитория"

    s = 40.0
    why: list[str] = []

    # --- Охват от подписчиков (ERR): ядро оценки. Норма 15–45%; >60% — флаг накрутки просмотров. ---
    if rr is not None:
        p = rr * 100
        if 15 <= p <= 45:
            s += 28; why.append(f"охват {p:.0f}% — живая аудитория")
        elif 10 <= p < 15:
            s += 13; why.append(f"охват {p:.0f}% — ниже нормы")
        elif 45 < p <= 60:
            s += 12; why.append(f"охват {p:.0f}% — высоковат")
        else:  # > 60%
            s -= 6; why.append(f"охват {p:.0f}% — проверить на накрутку просмотров")
    else:
        why.append("охват/подписчики неизвестны")

    # --- CPM: норма натив-посева ~150–350₽; дорого >600₽; слишком дёшево (<80₽) — подозрительно. ---
    if cpm:
        if cpm < 80:
            s += 4; why.append(f"CPM {cpm:.0f}₽ — подозрительно дёшево")
        elif cpm <= 350:
            s += 20; why.append(f"CPM {cpm:.0f}₽ — выгодно")
        elif cpm <= 600:
            s += 8; why.append(f"CPM {cpm:.0f}₽ — норма")
        elif cpm <= 1000:
            s -= 10; why.append(f"CPM {cpm:.0f}₽ — дороговато")
        else:
            s -= 22; why.append(f"CPM {cpm:.0f}₽ — дорого")
    else:
        why.append("цена не собрана")

    # --- Цитируемость: упоминания канала другими = органический авторитет/доверие. ---
    if mentions and mentions > 0:
        s += 6; why.append("есть упоминания в др. каналах")

    s = int(max(0, min(100, round(s))))
    verdict = "брать" if s >= 70 else ("осторожно" if s >= 50 else "мимо")
    # Слабый охват (<15%) не пускаем в «брать» даже при дешёвой цене — качество аудитории под вопросом.
    if rr is not None and rr < 0.15 and verdict == "брать":
        verdict = "осторожно"
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
