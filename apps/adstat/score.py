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

# Кусочно-линейные кривые бонусов (непрерывные → нет «ничьих» внутри банды). Калибровка по РЕАЛЬНЫМ
# перцентилям базы (см. замер 2026-06-30): ERR p10/50/90 = 3/11/39%, reaction_rate p10/50/90 = 0.3/0.68/2.3%.
_ERR_PTS = [(3, -14), (6, -4), (11, 6), (22, 18), (35, 24), (50, 16), (70, 2), (100, -8)]  # ERR=охват/подписч %
_RRATE_PTS = [(0.1, -8), (0.3, 0), (0.7, 8), (1.5, 16), (3, 20), (6, 14), (12, 2), (25, -8)]  # реакции/охват %: низко=накрутка просмотров, очень высоко=реакц-ферма
_FWD_PTS = [(0.02, 0), (0.1, 3), (0.3, 7), (1.0, 10), (3.0, 8)]  # форварды/охват % → ценность контента
# CPM₽ → бонус. M3: рекалибровано по РЕАЛЬНОМУ CPM (floor-цена telega / реальный охват tme),
# перцентили p10/50/90 = 493/1403/3246₽ — старая кривая (пик 150₽) штрафовала медианный канал на ~−20.
_CPM_PTS = [(150, 6), (350, 16), (550, 14), (900, 8), (1400, 2), (2300, -6), (3500, -16), (6000, -28)]

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


_SRC_RANK = {"tme": 4, "telethon": 3, "telemetr": 2}  # приоритет источника (telega/прочее → 1)


def _snap_key(s):
    """Ключ сортировки снапшота: сначала приоритет источника, потом свежесть (оба по убыванию)."""
    return (_SRC_RANK.get(getattr(s, "source", None), 1), getattr(s, "captured_at", None))


def _merge(snaps: list[dict]) -> dict:
    """Из снимков (УЖЕ отсортированы: приоритетный источник + свежесть впереди) берём первое не-None по полю.
    L1: telega-снимок больше не побеждает tme только потому, что свежее."""
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
    """Релевантность теме афиши по ключам. H2: АФИША проверяется ПЕРВОЙ («афиша побеждает мусор») — иначе
    off-topic-подстрока убивала настоящую афишу (ставк⊂вы­ставк → любой канал со словом «выставка» получал
    ×0.10). Только если афиша-ключа нет — режем мусор (×0.10). M7: город 0.85 / тема? 0.80, чтобы вердикт
    «брать» был достижим у сильных локальных/событийных каналов без точного ключевого слова."""
    t = f"{title or ''} {username or ''}".lower()
    if any(k in t for k in _AFISHA):
        return 1.0, "афиша"
    if any(k in t for k in _OFF_TOPIC):
        return 0.10, "не тема"
    if any(k in t for k in _CITY):
        return 0.85, "город/локалка"
    return 0.80, "тема?"  # прошёл discovery-гейт (не мусор) → не наказываем как мусор


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


def _city_alias_hit(alias: str, t: str) -> bool:
    """M6: латинский алиас матчим по границам ЛАТИНСКИХ букв (perm не ловится в su**perm**arket / **perm**anent,
    но ловится в afisha_perm / 'perm city'); кириллический стем — префикс, не предварённый кириллицей (ловит
    инфлексии «москва/московский», но не середину слова)."""
    if alias.isascii():
        return re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", t) is not None
    return re.search(r"(?<![а-я])" + re.escape(alias), t) is not None


def infer_city(title: str | None, username: str | None, hint: str | None = None) -> str | None:
    """Город канала (каноническое имя) из подсказки discovery / названия+username. Несколько разных → None."""
    if hint:
        return hint
    t = f"{title or ''} {username or ''}".lower()
    matched = {name for alias, name in _CITY_ALIASES.items() if _city_alias_hit(alias, t)}
    return next(iter(matched)) if len(matched) == 1 else None


def score_channel(m: dict) -> tuple[int, str, str]:
    """КАЧЕСТВО канала (0–100) по ВСЕМ доступным сигналам, без релевантности (её применяет rank).
    Непрерывно. Сигналы: ERR (охват/подписч), reaction_rate (реакции/охват — анти-накрутка, боты не
    реагируют), forward_rate (форварды/охват — ценность контента), частота постинга, CPM, упоминания.
    Каждый сигнал учитывается ТОЛЬКО если собран — формула деградирует мягко на бедных данных."""
    subs = m.get("subscribers")
    reach = m.get("avg_reach")
    cpm = m.get("cpm")
    price = m.get("post_price")
    reactions = m.get("avg_reactions")
    fwd = m.get("avg_forwards")
    ppw = m.get("posts_per_week")
    mentions = m.get("mentions")
    fraud = m.get("is_scam") or m.get("is_boosting") or m.get("sanctioned")
    if cpm is None and price and reach:
        cpm = price / reach * 1000.0
    if fraud:
        return 0, "мимо", "фрод-флаг (scam / накрутка / санкции)"

    s = 40.0
    why: list[str] = []
    err = (reach / subs * 100) if (subs and reach) else None  # ERR %
    if err is None:  # M5: фолбэк на готовый ER от источника (telethon/telemetr/telega, уже в %), если своего нет
        fallback = m.get("er") or m.get("err")
        err = float(fallback) if fallback else None
    if err is not None:
        s += _lerp(_ERR_PTS, err)
        why.append(f"ERR {err:.0f}%")
    else:
        why.append("ERR неизвестен")

    rr = (reactions / reach * 100) if (reactions and reach) else None  # реакции/охват %
    if rr is not None:
        s += _lerp(_RRATE_PTS, rr)
        why.append(f"реакции {rr:.1f}%" + (" — мало к просмотрам (накрутка?)" if rr < 0.3 else ""))

    fr = (fwd / reach * 100) if (fwd and reach) else None  # форварды/охват %
    if fr is not None:
        s += _lerp(_FWD_PTS, fr)
        if fr >= 0.5:
            why.append(f"форварды {fr:.1f}%")

    if ppw is not None:  # частота постинга, постов/нед
        s += -10 if ppw < 1 else -2 if ppw < 3 else 4 if ppw <= 25 else 0 if ppw <= 50 else -8
        if ppw < 1:
            why.append("почти не постит")
        elif ppw > 50:
            why.append("частит — спам?")

    if cpm:
        s += _lerp(_CPM_PTS, cpm)
        why.append(f"CPM {cpm:.0f}₽" + (" — дёшево" if cpm < 80 else (" — дорого" if cpm > 600 else "")))
    else:
        why.append("цена не собрана")
    if mentions and mentions > 0:
        s += 5

    s = int(max(0, min(100, round(s))))
    verdict = "брать" if s >= 70 else ("осторожно" if s >= 50 else "мимо")
    # Подстраховка: очень низкий ERR без подтверждённой реакциями живости → не «брать» (могла быть накрутка).
    if err is not None and err < 8 and (rr is None or rr < 0.3) and verdict == "брать":
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
        best_reach = dict(db.execute(text(
            "SELECT DISTINCT ON (channel_id) channel_id, avg_reach FROM adstat.snapshots "
            f"WHERE avg_reach IS NOT NULL ORDER BY channel_id, {_rank} DESC, captured_at DESC"
        )).all())
        best_react = dict(db.execute(text(
            "SELECT DISTINCT ON (channel_id) channel_id, avg_reactions FROM adstat.snapshots "
            f"WHERE avg_reactions IS NOT NULL ORDER BY channel_id, {_rank} DESC, captured_at DESC"
        )).all())
        # M1/M2: лучший снапшот ПО ПОДПИСЧИКАМ (источник-приоритет) — подписчики авторитетны (tme>telega),
        # а охват+реакции берём из ТОЙ ЖЕ строки, если они там есть → ERR/reaction_rate когерентны (один замер).
        # Если в этой строке нет охвата — падаем на лучший охват по источнику отдельно (без регресса подписчиков).
        best_snap = {r[0]: (r[1], r[2], r[3]) for r in db.execute(text(
            "SELECT DISTINCT ON (channel_id) channel_id, subscribers, avg_reach, avg_reactions FROM adstat.snapshots "
            f"WHERE subscribers IS NOT NULL ORDER BY channel_id, {_rank} DESC, captured_at DESC"
        )).all()}
        # forwards / частота постинга — из последнего telethon-снапшота (raw JSONB).
        tele = dict(db.execute(text(
            "SELECT DISTINCT ON (channel_id) channel_id, raw FROM adstat.snapshots "
            "WHERE source = 'telethon' AND raw IS NOT NULL ORDER BY channel_id, captured_at DESC"
        )).all())
        # Подсказка города из discovery (явный запрос «афиша <город>») — высшая уверенность.
        target_city = dict(db.execute(text("SELECT username, city FROM adstat.targets WHERE city IS NOT NULL AND city <> ''")).all())
        channels = db.execute(select(AdChannel)).scalars().all()
        for ch in channels:
            if not ch.username or not _VALID_USERNAME.match(ch.username):
                continue
            snaps = sorted(db.execute(  # L1: приоритет источника + свежесть (а не только свежесть)
                select(AdSnapshot).where(AdSnapshot.channel_id == ch.channel_id)
                .order_by(AdSnapshot.captured_at.desc()).limit(10)
            ).scalars().all(), key=_snap_key, reverse=True)
            m = _merge([{f: getattr(s, f, None) for f in _FIELDS} for s in snaps])
            bs = best_snap.get(ch.channel_id)
            if bs:
                m["subscribers"] = bs[0]  # авторитетные подписчики (источник-приоритет)
                m["avg_reach"] = bs[1] if bs[1] is not None else best_reach.get(ch.channel_id)
                m["avg_reactions"] = bs[2] if bs[2] is not None else best_react.get(ch.channel_id)
            else:  # нет снапшота с подписчиками — берём лучший охват/реакции по источнику отдельно
                if best_reach.get(ch.channel_id):
                    m["avg_reach"] = best_reach[ch.channel_id]
                if best_react.get(ch.channel_id):
                    m["avg_reactions"] = best_react[ch.channel_id]
            tr = tele.get(ch.channel_id)
            if isinstance(tr, dict):
                if tr.get("avg_forwards") is not None:
                    m["avg_forwards"] = tr["avg_forwards"]
                if tr.get("posts_per_week") is not None:
                    m["posts_per_week"] = tr["posts_per_week"]
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
            snaps = sorted(db.execute(  # L1: приоритет источника + свежесть (а не только свежесть)
                select(AdSnapshot).where(AdSnapshot.channel_id == ch.channel_id)
                .order_by(AdSnapshot.captured_at.desc()).limit(10)
            ).scalars().all(), key=_snap_key, reverse=True)
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
