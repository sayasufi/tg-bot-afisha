"""Discovery — автопоиск афиша-каналов через Telemetr search по ключевым запросам.

Гоняет keyword×город запросы → объединяет → дедуп → пишет в adstat.targets и сразу снимок
(search отдаёт подписчиков/ER/is_scam/sanctioned, так что discover = «найти + снять» за один проход).
Запуск: python -m apps.adstat.run --discover   (или флоу discover-adstat).
"""
from __future__ import annotations

import logging
import re
import time

from core.config.settings import get_settings

from apps.adstat.service import persist_snapshots, upsert_targets
from apps.adstat.telemetr import TelemetrClient

log = logging.getLogger(__name__)

# Базовые тематические термины (без города — ловят федеральные/крупные афиши).
_BASE_TERMS = [
    "афиша", "куда сходить", "куда пойти", "события города", "концерты афиша",
    "выставки", "мероприятия", "что посмотреть", "театр", "фестивали", "развлечения",
]
# Термины, которые комбинируем с каждым городом (афиша-специфичные → меньше город-новостного шума).
_CITY_TERMS = ["афиша", "куда сходить", "куда пойти", "события", "концерты", "театр",
               "выставки", "развлечения", "выходные", "фестиваль"]
# Город в запросе → каноничное имя для adstat.targets.city.
_CITIES = {
    "москва": "Москва", "спб": "Санкт-Петербург", "питер": "Санкт-Петербург",
    "екатеринбург": "Екатеринбург", "новосибирск": "Новосибирск", "казань": "Казань",
    "нижний новгород": "Нижний Новгород", "челябинск": "Челябинск", "самара": "Самара",
    "уфа": "Уфа", "ростов": "Ростов-на-Дону", "краснодар": "Краснодар", "пермь": "Пермь",
    "воронеж": "Воронеж", "волгоград": "Волгоград", "красноярск": "Красноярск", "омск": "Омск",
}


def _queries() -> list[tuple[str, str | None]]:
    qs: list[tuple[str, str | None]] = [(t, None) for t in _BASE_TERMS]
    for c_term, c_name in _CITIES.items():
        for t in _CITY_TERMS:
            qs.append((f"{t} {c_term}", c_name))
    return qs


def discover(min_subscribers: int = 2000, dry_run: bool = False) -> list[dict]:
    """Найти афиша-каналы и (если не dry_run) записать targets + снимки."""
    settings = get_settings()
    if not dry_run and not settings.adstat_enabled:
        log.info("adstat discover: ADSTAT_ENABLED=false — пропуск")
        return []
    client = TelemetrClient(settings.adstat_cookies_path)
    if not client.ready:
        log.warning("adstat discover: нет Telemetr-сессии (куки?)")
        return []

    from apps.adstat.score import _relevance

    found: dict[str, tuple[dict, str | None]] = {}
    queries = _queries()
    for query, city in queries:
        for it in client.search(query):
            un = (it.get("username") or "").lower()
            if not un or (it.get("subscribers") or 0) < min_subscribers:
                continue
            if _relevance(it.get("title"), un)[1] == "не тема":  # отсев off-topic (keyword-коллизии: маникюр/крипто/эзо)
                continue
            if un not in found:
                found[un] = (it, city)
            elif city and not found[un][1]:
                found[un] = (found[un][0], city)  # сохраняем статистику, добавляем город
        time.sleep(settings.adstat_delay_sec)

    rows = [row for row, _ in found.values()]
    targets = [{"username": un, "city": city} for un, (_, city) in found.items()]
    log.info("adstat discover: %d уникальных каналов из %d запросов (min_subs=%d)",
             len(rows), len(queries), min_subscribers)
    if not dry_run:
        upsert_targets(targets)
        persist_snapshots(rows)
    return rows


# Категория 52 «Культура и события» широкая — большинство афиша-каналов названы по городу (без слова
# «афиша»), поэтому фильтруем НЕ включением, а ИСКЛЮЧЕНИЕМ явных федеральных новостников/агрегаторов.
# Остальное (культура/события/городские/лайфстайл) оставляем; «чистую афишу» можно добрать по названию.
_NEWS_RE = re.compile(
    r"новост|\bnews\b|\bчп\b|происшеств|инцидент|\bбаза\b|\bbaza\b|\bmash\b|readovka|"
    r"topor|\bshot\b|двач|\b2ch\b|сводк|оперативн|незыгар|кремл|политик|war|воен",
    re.I,
)


def _is_afisha(r: dict) -> bool:
    """True, если канал НЕ выглядит федеральным новостником (оставляем культуру/события/городские)."""
    t = (r.get("title") or "") + " " + (r.get("username") or "")
    return not _NEWS_RE.search(t)


def discover_telega(category_id: int = 52, max_pages: int = 60, with_prices: bool = True,
                    afisha_only: bool = True, dry_run: bool = False) -> list[dict]:
    """Telega.in: каталог афиша-категории + реальная цена размещения + CPM.
    category_id=52 = «Культура и события»; afisha_only отсекает новостники по названию."""
    settings = get_settings()
    if not dry_run and not settings.adstat_enabled:
        log.info("adstat discover_telega: ADSTAT_ENABLED=false — пропуск")
        return []
    from apps.adstat.telega import TelegaClient

    client = TelegaClient()
    rows = client.discover(category_id, max_pages)
    total = len(rows)
    if afisha_only:
        from apps.adstat.score import _relevance
        # _is_afisha режет федеральных новостников; _relevance добивает off-topic (мусор), оставляя афишу+город.
        rows = [r for r in rows if _is_afisha(r) and _relevance(r.get("title"), r.get("username"))[1] != "не тема"]
    if with_prices and rows:
        rows = client.enrich_prices(rows)
    for r in rows:  # CPM = цена / охват × 1000
        if r.get("post_price") and r.get("avg_reach"):
            r["cpm"] = round(r["post_price"] / r["avg_reach"] * 1000, 1)
    log.info("adstat discover_telega: %d/%d афиша-каналов (cat=%d, цены=%s)",
             len(rows), total, category_id, with_prices)
    if not dry_run:
        upsert_targets([{"username": r["username"], "city": None} for r in rows])
        persist_snapshots(rows)
    return rows


def enrich_shortlist_prices(top_n: int = 50, dry_run: bool = False) -> int:
    """Добрать РЕАЛЬНУЮ цену поста (telega card) по топ-АФИША каналам, у которых ещё нет CPM → CPM завершается
    → score переводит их в «брать». Цены не тянем на тысячи ежедневно (дорого), а добиваем точечно по шорт-листу.
    Кто не на бирже telega — цена None (пропуск)."""
    settings = get_settings()
    if not dry_run and not settings.adstat_enabled:
        log.info("adstat enrich_shortlist_prices: ADSTAT_ENABLED=false — пропуск")
        return 0
    from apps.adstat.score import rank
    from apps.adstat.telega import TelegaClient

    # M9: добираем цену и для «город/локалка» (ключевые гео-цели афиши, дешевле и точнее), не только «афиша»;
    # min_reach пониже, чтобы шортлист не запирался на reach≥2000.
    cands = [r for r in rank(min_reach=300, limit=400)
             if r.get("relevance") in ("афиша", "город/локалка") and not r.get("cpm")][:top_n]
    if not cands:
        log.info("adstat enrich_shortlist_prices: нет on-topic-кандидатов без цены")
        return 0
    client = TelegaClient()
    cand_rows = [{"source": "telega", "username": r["username"], "avg_reach": r.get("reach"),
                  "subscribers": r.get("subscribers")} for r in cands]
    priced = client.enrich_prices(cand_rows)  # параллельно тянет post_price с card-страниц
    rows = [r for r in priced if r.get("post_price")]
    for r in rows:  # CPM = цена / охват × 1000
        if r.get("avg_reach"):
            r["cpm"] = round(r["post_price"] / r["avg_reach"] * 1000, 1)
    log.info("adstat enrich_shortlist_prices: %d/%d афиша-каналов получили цену", len(rows), len(cands))
    if not dry_run and rows:
        persist_snapshots(rows)
    return len(rows)
