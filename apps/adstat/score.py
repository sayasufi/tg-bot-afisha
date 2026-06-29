"""Скоринг каналов «брать / осторожно / мимо» для закупки рекламы (посев) афиша-приложения.

ДВА слоя:
  1. КАЧЕСТВО рекламы (метрики, по консенсусу индустрии — eLama/Bidfox/TGStat/Telemetr):
     - охват/подписчики (ERR) — ядро живости: норма 15–45%; <10% → мёртвая/купленная («мимо»);
       >60% → флаг накрутки просмотров. Кривая непрерывная (пик ~30%), чтобы ранжировать тонко.
     - CPM (₽/1000 просмотров): медиана натив-посева ~150–180₽; дорого >600₽; слишком дёшево (<80₽)
       тоже подозрительно (плохая аудитория). Тоже непрерывно.
     - упоминания/цитируемость → бонус; фрод (scam/накрутка/санкции) → 0.
  2. РЕЛЕВАНТНОСТЬ теме (Окрест = афиша/события): по ключам в названии/юзернейме.
     афиша/культура ×1.0, город/локалка-новости ×0.8, мусор (ногти/дача/эзотерика/политика…) ×0.1.
  ИТОГ = качество × релевантность → так «топ каналов вообще» превращается в «топ ДЛЯ афиша-приложения».
"""
from __future__ import annotations

import re

from sqlalchemy import select

from apps.adstat.models import AdChannel, AdSnapshot
from core.db.session import SessionLocal

_FIELDS = ["subscribers", "avg_reach", "avg_reactions", "er", "err", "cpm", "post_price", "rating",
           "is_scam", "is_boosting", "sanctioned", "quality_score", "mentions"]

# Кусочно-линейные кривые бонусов (непрерывные → нет «ничьих» внутри банды).
_REACH_PTS = [(10, 4), (15, 16), (30, 28), (45, 16), (60, -2), (100, -12)]  # охват% подписчиков → бонус
_CPM_PTS = [(50, 2), (80, 8), (150, 20), (300, 18), (500, 6), (800, -10), (1500, -22)]  # CPM₽ → бонус

# Релевантность теме афиши. Проверяется по lower(title+username); порядок: мусор → афиша → город → нейтрально.
_OFF_TOPIC = (
    "маникюр", "manik", "ногт", "nogt", "ресниц", "брови", "дача", "dacha", "огород", "ogorod", "грядк",
    "рассад", "рецепт", "recept", "кулинар", "kulinar", "похуд", "pohud", "фитнес", "fitnes", "диет",
    "экстрасенс", "ekstrasens", "extrasens", "гороскоп", "goroskop", "таро", "магия", "эзотер", "ezoter",
    "заработок", "zarabotok", "крипт", "kript", "crypto", "инвест", "invest", "форекс", "forex", "ставк",
    "casino", "казино", "букмекер", "политик", "politik", "putin", "навальн", "шаблон", "shablon", "мотивац",
    "цитат", "психолог", "psiholog", "знакомств", "znakomstv", "18+", "adult", "porn", "порн", "нумеролог",
    "поздравл", "pozdrav", "открытк", "otkrytk", "саморазвит", "мемы", "memes",
    "вязани", "vyazanie", "крючк", "амигуруми", "вышивк", "рукодели", "поделк", "diy",
    "недвиж", "новостройк", "ипотек", "ремонт", "репетитор", "егэ", "огэ", "wildberries", "ozon",
    "мантр", "чакр", "ведьм", "гадани", "рейки", "автоблог", "запчаст",
)
_AFISHA = (
    "афиш", "afish", "кудасход", "кудапо", "kuda", "событи", "concert", "концерт", "театр", "teatr",
    "выставк", "vystavk", "кинотеатр", "кинопоказ", "киноклуб", "фестивал", "festival", "спектакл", "билет", "bilet", "анонс",
    "anons", "гастрол", "стендап", "standup", "вечеринк", "тусовк", "tusovk", "досуг", "развлечен",
    "культур", "kultur", "экскурс", "ekskurs", "лекци", "мероприят", "выходны", "weekend",
    # B3-добор: культурно-событийные ниши, проваливавшиеся в «тема?»
    "праздник", "ярмарк", "квиз", "квест", "опенэйр", "open air", "перформанс", "иммерс", "мюзикл",
    "опер", "балет", "джаз", "рейв", "караоке", "квартирник", "артхаус", "артспейс", "креативн",
    "куда пойти", "куда сходить", "путешеств", "туризм", "набережн",
)
_CITY = (
    "новост", "novost", "news", "чп", "chp", "происшеств", "инцидент", "incident", "типичн", "tipich",
    "подслушан", "podslushan", "городск", "gorod", "област", "oblast", "регион", "region",
)


def _merge(snaps: list[dict]) -> dict:
    """Из снимков (свежие первыми) берём первое не-None по каждому полю."""
    m: dict = {}
    for key in _FIELDS:
        for s in snaps:
            if s.get(key) is not None:
                m[key] = s[key]
                break
    return m


def _lerp(pts: list[tuple[float, float]], x: float) -> float:
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def _relevance(title: str | None, username: str | None) -> tuple[float, str]:
    """Релевантность теме афиши по ключам. Мусор режем (×0.1), афишу поднимаем (×1.0), город — середина."""
    t = f"{title or ''} {username or ''}".lower()
    if any(k in t for k in _OFF_TOPIC):
        return 0.10, "не тема"
    if any(k in t for k in _AFISHA):
        return 1.0, "афиша"
    if any(k in t for k in _CITY):
        return 0.75, "город/локалка"  # локальная аудитория — годная вторичная цель (B3: 0.6→0.75)
    return 0.65, "тема?"  # прошёл discovery-гейт (не мусор) → не наказываем как мусор (B3: 0.5→0.65)


# Алиас → каноническое имя города (как в discover._CITIES / core.domain.cities.name). Полные стемы —
# чтобы Краснодар↔Красноярск не путались (общий префикс не матчим). Несколько разных городов в тексте → None.
_CITY_ALIASES: dict[str, str] = {
    "москв": "Москва", "moskv": "Москва", "moscow": "Москва", "мск": "Москва",
    "петербург": "Санкт-Петербург", "питер": "Санкт-Петербург", "спб": "Санкт-Петербург", "spb": "Санкт-Петербург", "piter": "Санкт-Петербург",
    "екатеринбург": "Екатеринбург", "ekaterinburg": "Екатеринбург", "екб": "Екатеринбург", "ekb": "Екатеринбург",
    "новосиб": "Новосибирск", "novosib": "Новосибирск",
    "казан": "Казань", "kazan": "Казань",
    "нижнийновгород": "Нижний Новгород", "нижний": "Нижний Новгород", "нижегород": "Нижний Новгород", "ннов": "Нижний Новгород", "nnov": "Нижний Новгород",
    "челябинск": "Челябинск", "chelyab": "Челябинск",
    "самар": "Самара", "samara": "Самара",
    "уфа": "Уфа", "ufa": "Уфа",
    "ростовнадону": "Ростов-на-Дону", "ростов": "Ростов-на-Дону", "rostov": "Ростов-на-Дону",
    "краснодар": "Краснодар", "krasnodar": "Краснодар", "кубан": "Краснодар",
    "пермь": "Пермь", "perm": "Пермь",
    "воронеж": "Воронеж", "voronezh": "Воронеж",
    "волгоград": "Волгоград", "volgograd": "Волгоград",
    "красноярск": "Красноярск", "krasnoyarsk": "Красноярск", "крск": "Красноярск",
    "омск": "Омск", "omsk": "Омск",
}


def infer_city(title: str | None, username: str | None, hint: str | None = None) -> str | None:
    """Город канала (каноническое имя) из подсказки discovery / названия+username. Несколько разных → None."""
    if hint:
        return hint
    t = f"{title or ''} {username or ''}".lower()
    matched = {name for alias, name in _CITY_ALIASES.items() if alias in t}
    return next(iter(matched)) if len(matched) == 1 else None


def score_channel(m: dict) -> tuple[int, str, str]:
    """КАЧЕСТВО канала (0–100) по метрикам, без релевантности (её применяет rank). Непрерывное."""
    subs = m.get("subscribers")
    reach = m.get("avg_reach")
    cpm = m.get("cpm")
    price = m.get("post_price")
    mentions = m.get("mentions")
    fraud = m.get("is_scam") or m.get("is_boosting") or m.get("sanctioned")
    if cpm is None and price and reach:
        cpm = price / reach * 1000.0

    if fraud:
        return 0, "мимо", "фрод-флаг (scam / накрутка / санкции)"
    rr = (reach / subs) if (subs and reach) else None  # ERR = охват/подписчики
    if rr is not None and rr < 0.10:
        return 8, "мимо", f"охват {rr * 100:.0f}% подписчиков (<10%) — мёртвая/купленная аудитория"

    s = 40.0
    why: list[str] = []
    if rr is not None:
        p = rr * 100
        s += _lerp(_REACH_PTS, p)
        why.append(f"охват {p:.0f}%" + (" — проверить накрутку" if p > 60 else ""))
    else:
        why.append("охват неизвестен")
    if cpm:
        s += _lerp(_CPM_PTS, cpm)
        why.append(f"CPM {cpm:.0f}₽" + (" — дёшево, проверить" if cpm < 80 else ("" if cpm <= 600 else " — дорого")))
    else:
        why.append("цена не собрана")
    if mentions and mentions > 0:
        s += 6
        why.append("есть упоминания")
    # Реакции — сильный сигнал ЖИВОЙ аудитории (боты не реагируют). Бонус за долю реакций от охвата.
    reactions = m.get("avg_reactions")
    if reactions and reach:
        rrate = reactions / reach
        if rrate >= 0.005:  # ≥0.5% реакций от просмотров
            s += min(8.0, rrate * 400)
            why.append(f"реакции {rrate * 100:.1f}%")

    s = int(max(0, min(100, round(s))))
    verdict = "брать" if s >= 70 else ("осторожно" if s >= 50 else "мимо")
    if rr is not None and rr < 0.15 and verdict == "брать":
        verdict = "осторожно"
    return s, verdict, ", ".join(why) or "мало данных"


# Валидный публичный TG-username (5–32, буквы/цифры/подчёркивание). Мусорные/закодированные значения
# (напр. 43-символьные строки у приватных каналов) рекламой не закупишь → в шорт-лист не берём.
_VALID_USERNAME = re.compile(r"^[A-Za-z0-9_]{4,32}$")


def recompute_scores() -> dict:
    """Пересчитать НАШ скор (качество×релевантность) на НАДЁЖНЫХ подписчиках (t.me/telethon приоритетнее
    устаревшего каталога Telega) и записать на канал (adstat.channels.score/quality/verdict/relevance).
    Качество зависит от ERR=охват/подписчики → с корректными подписчиками скор становится правдивым."""
    from sqlalchemy import text

    n = 0
    with SessionLocal() as db:
        _rank = "(CASE source WHEN 'tme' THEN 4 WHEN 'telethon' THEN 3 WHEN 'telemetr' THEN 2 ELSE 1 END)"
        best = dict(db.execute(text(
            "SELECT DISTINCT ON (channel_id) channel_id, subscribers FROM adstat.snapshots "
            f"WHERE subscribers IS NOT NULL ORDER BY channel_id, {_rank} DESC, captured_at DESC"
        )).all())
        best_reach = dict(db.execute(text(
            "SELECT DISTINCT ON (channel_id) channel_id, avg_reach FROM adstat.snapshots "
            f"WHERE avg_reach IS NOT NULL ORDER BY channel_id, {_rank} DESC, captured_at DESC"
        )).all())
        # Подсказка города из discovery (явный запрос «афиша <город>») — высшая уверенность.
        target_city = dict(db.execute(text("SELECT username, city FROM adstat.targets WHERE city IS NOT NULL AND city <> ''")).all())
        channels = db.execute(select(AdChannel)).scalars().all()
        for ch in channels:
            if not ch.username or not _VALID_USERNAME.match(ch.username):
                continue
            snaps = db.execute(
                select(AdSnapshot).where(AdSnapshot.channel_id == ch.channel_id)
                .order_by(AdSnapshot.captured_at.desc()).limit(10)
            ).scalars().all()
            m = _merge([{f: getattr(s, f, None) for f in _FIELDS} for s in snaps])
            if best.get(ch.channel_id):
                m["subscribers"] = best[ch.channel_id]   # надёжные подписчики (t.me/telethon)
            if best_reach.get(ch.channel_id):
                m["avg_reach"] = best_reach[ch.channel_id]  # реальный охват (просмотры постов с t.me/s)
            m["cpm"] = None  # пересчитать CPM из реальных цена/охват, а не брать каталожный
            quality, _qv, _why = score_channel(m)
            rel, rel_label = _relevance(ch.title, ch.username)
            final = int(round(quality * rel))
            verdict = "брать" if final >= 70 else ("осторожно" if final >= 50 else "мимо")
            city = infer_city(ch.title, ch.username, target_city.get(ch.username))
            db.execute(text(
                "UPDATE adstat.channels SET score=:s, quality=:q, verdict=:v, relevance=:r, city=:city, score_at=now() "
                "WHERE channel_id=:cid"
            ), {"s": final, "q": quality, "v": verdict, "r": rel_label, "city": city, "cid": ch.channel_id})
            n += 1
        db.commit()
    return {"scored": n}


def rank(min_reach: int = 2000, limit: int = 100) -> list[dict]:
    out: list[dict] = []
    with SessionLocal() as db:
        channels = db.execute(select(AdChannel)).scalars().all()
        for ch in channels:
            if not ch.username or not _VALID_USERNAME.match(ch.username):
                continue
            snaps = db.execute(
                select(AdSnapshot).where(AdSnapshot.channel_id == ch.channel_id)
                .order_by(AdSnapshot.captured_at.desc()).limit(10)
            ).scalars().all()
            m = _merge([{f: getattr(s, f, None) for f in _FIELDS} for s in snaps])
            if not m.get("avg_reach") or m["avg_reach"] < min_reach:
                continue
            quality, _qv, why = score_channel(m)
            rel, rel_label = _relevance(ch.title, ch.username)
            final = int(round(quality * rel))  # ИТОГ = качество × релевантность
            verdict = "брать" if final >= 70 else ("осторожно" if final >= 50 else "мимо")
            out.append({
                "username": ch.username, "title": ch.title, "score": final, "quality": quality,
                "relevance": rel_label, "verdict": verdict, "reason": f"{why} · {rel_label}",
                "subscribers": m.get("subscribers"), "reach": m.get("avg_reach"),
                "er": m.get("er") or m.get("err"), "cpm": m.get("cpm"), "price": m.get("post_price"),
            })
    out.sort(key=lambda x: -x["score"])
    return out[:limit]
