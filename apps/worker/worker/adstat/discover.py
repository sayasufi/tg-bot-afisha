"""Discovery — автопоиск афиша-каналов через Telemetr search по ключевым запросам.

Гоняет keyword×город запросы → объединяет → дедуп → пишет в adstat.targets и сразу снимок
(search отдаёт подписчиков/ER/is_scam/sanctioned, так что discover = «найти + снять» за один проход).
Запуск: python -m apps.worker.worker.adstat.run --discover   (или флоу discover-adstat).
"""
from __future__ import annotations

import logging
import time

from core.config.settings import get_settings

from apps.worker.worker.adstat.service import persist_snapshots, upsert_targets
from apps.worker.worker.adstat.telemetr import TelemetrClient

log = logging.getLogger(__name__)

# Базовые тематические термины (без города — ловят федеральные/крупные афиши).
_BASE_TERMS = [
    "афиша", "куда сходить", "куда пойти", "события города",
    "концерты афиша", "выставки", "мероприятия", "что посмотреть",
]
# Термины, которые комбинируем с каждым городом.
_CITY_TERMS = ["афиша", "куда сходить", "события"]
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

    found: dict[str, tuple[dict, str | None]] = {}
    queries = _queries()
    for query, city in queries:
        for it in client.search(query):
            un = (it.get("username") or "").lower()
            if not un or (it.get("subscribers") or 0) < min_subscribers:
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


def discover_telega(category_id: int = 52, max_pages: int = 60,
                    with_prices: bool = True, dry_run: bool = False) -> list[dict]:
    """Telega.in: каталог афиша-категории (тысячи каналов) + реальная цена размещения поста.
    category_id=52 = «Культура и события» (Афиша/Концерты/Выставки/Музеи)."""
    settings = get_settings()
    if not dry_run and not settings.adstat_enabled:
        log.info("adstat discover_telega: ADSTAT_ENABLED=false — пропуск")
        return []
    from apps.worker.worker.adstat.telega import TelegaClient

    client = TelegaClient()
    rows = client.discover(category_id, max_pages)
    if with_prices and rows:
        rows = client.enrich_prices(rows)
    log.info("adstat discover_telega: %d каналов (cat=%d, цены=%s)", len(rows), category_id, with_prices)
    if not dry_run:
        upsert_targets([{"username": r["username"], "city": None} for r in rows])
        persist_snapshots(rows)
    return rows
