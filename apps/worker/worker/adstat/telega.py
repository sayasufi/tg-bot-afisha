"""Telega.in — биржа Telegram-рекламы. Публичный каталог (без логина, без Cloudflare).

Фильтр категории РАБОТАЕТ ТОЛЬКО через путь-слаг `/catalog/<url_name>?page=N` — query-param
`?categories[]=<id>` telega.in ИГНОРИРУЕТ и молча отдаёт ДЕФОЛТНЫЙ неотфильтрованный каталог
(шопинг/регион-новости). Слаг афиши = `culture_and_events` (id 52, «Культура и события»; таксономия
плоская, ~44 темы, более узкой афиша-категории НЕТ). Из карточки каталога снимаем подписчиков/охват/ERR;
РЕАЛЬНУЮ цену размещения — со страницы канала /channels/<username>/card.
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import re

from curl_cffi import requests as creq

log = logging.getLogger(__name__)

_H = {"Accept-Language": "ru-RU,ru;q=0.9"}
_RUB = "₽"
CATEGORY_AFISHA = 52  # culture_and_events (id для совместимости вызовов; в URL идёт слаг — см. _SLUG)
# id → url_name слаг. Фильтр работает только путём, поэтому маппим id в слаг. culture_and_events — афиша.
_SLUG = {
    52: "culture_and_events", 43: "art_and_design", 25: "music", 27: "movies",
    15: "recreation_and_entertainment",
}


def _f(s: str | None):
    return float(s) if s else None


class TelegaClient:
    SOURCE = "telega"

    @property
    def ready(self) -> bool:
        return True  # публичный источник, куки не нужны

    def _get(self, url: str) -> str:
        return creq.get(url, impersonate="chrome", timeout=30, headers=_H).text

    def catalog_page(self, category_id: int, page: int) -> list[dict]:
        slug = _SLUG.get(category_id, category_id)  # фильтр категории работает ТОЛЬКО через путь-слаг
        t = self._get(f"https://telega.in/catalog/{slug}?page={page}")
        out: dict[str, dict] = {}
        for chunk in t.split('class="about-avatar')[1:]:
            mu = re.search(r"/channels/([A-Za-z0-9_]+)/card", chunk)
            if not mu:
                continue
            u = mu.group(1)
            if u in out:
                continue

            def g(attr: str):
                m = re.search(attr + r'="([\d.]+)"', chunk)
                return m.group(1) if m else None

            cnt, reach, err = g("data-count"), g("data-avg-post-reach"), g("data-err-percent")
            rating = g("data-raiting")
            mt = re.search(r'channel_title[\s\S]{0,140}?title="([^"]+)"', chunk)
            title = mt.group(1) if mt else None
            out[u] = {
                "source": self.SOURCE, "username": u, "title": title,
                "subscribers": int(float(cnt)) if cnt else None,
                "avg_reach": int(float(reach)) if reach else None,
                "err": _f(err), "rating": _f(rating),
                "raw": {"telega_catalog": {"subscribers": cnt, "reach": reach, "err": err,
                                           "rating": rating, "title": title}},
            }
        return list(out.values())

    def discover(self, category_id: int = CATEGORY_AFISHA, max_pages: int = 60) -> list[dict]:
        """Пройти каталог категории постранично, собрать уникальные каналы."""
        found: dict[str, dict] = {}
        for pg in range(1, max_pages + 1):
            try:
                rows = self.catalog_page(category_id, pg)
            except Exception as e:  # noqa: BLE001
                log.warning("telega catalog page %d: %s", pg, e)
                break
            new = [r for r in rows if r["username"] not in found]
            if not rows or not new:  # пагинация закончилась / пошли повторы
                break
            for r in new:
                found[r["username"]] = r
        log.info("telega: каталог категории %d → %d каналов (до %d стр.)", category_id, len(found), max_pages)
        return list(found.values())

    def fetch_price(self, username: str) -> float | None:
        """Стоимость размещения поста (₽) со страницы канала."""
        try:
            c = self._get(f"https://telega.in/channels/{username}/card")
        except Exception:  # noqa: BLE001
            return None
        m = re.search(r"Стоимость размещения составляет\s*([\d\s., ]+?)\s*" + _RUB, c)
        if not m:
            return None
        raw = m.group(1).replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            return None

    def enrich_prices(self, rows: list[dict], workers: int = 8) -> list[dict]:
        """Дозалить реальную цену поста по каждому каналу (card-страницы, конкурентно)."""
        def one(r: dict) -> dict:
            r["post_price"] = self.fetch_price(r["username"])
            return r

        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(one, rows))

    # единичный fetch для совместимости со scrape() (refresh по username)
    def fetch(self, username: str) -> dict:
        u = username.lstrip("@")
        for pg in (1,):  # цена + по возможности охват с card-страницы недоступны без каталога;
            pass
        price = self.fetch_price(u)
        return {"source": self.SOURCE, "username": u, "post_price": price}
