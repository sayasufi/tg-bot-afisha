"""Telemetr — клиент каталог-API (чистый JSON, без Cloudflare, серверо-готов).

Поиск/резолвинг по username универсальный (работает и с кириллицей):
  GET /api/v1/catalog/channels/search?query=<q>  → username, peer_id, subscribers, er, is_scam, sanctioned
Обогащение деталями (по совпадению peer_id, best-effort — title-поиск латиницей):
  GET /api/v1/catalog/channels?title=<title>     → quality, premium_subs, month_growth, ad_price,
                                                    language, is_boosting, is_stolen
"""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

from curl_cffi import requests as creq

from apps.adstat.cookies import load_netscape_cookies

log = logging.getLogger(__name__)

_BASE = "https://telemetr.me/api/v1/catalog/channels"
_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://telemetr.me/catalog",
    "Accept": "application/json, text/plain, */*",
}


class TelemetrClient:
    SOURCE = "telemetr"

    def __init__(self, cookies_path: str):
        self._cookies = load_netscape_cookies(cookies_path, "telemetr.me")

    @property
    def ready(self) -> bool:
        return bool(self._cookies.get("PHPSESSID"))

    def _get(self, url: str):
        return creq.get(url, cookies=self._cookies, headers=_HEADERS, impersonate="chrome", timeout=30)

    @staticmethod
    def _parse_item(it: dict) -> dict:
        s = it.get("statistics", {}) or {}
        subs = ((s.get("subscribers", {}) or {}).get("count", {}) or {}).get("total")
        return {
            "source": TelemetrClient.SOURCE,
            "username": ((it.get("links") or {}).get("userName") or ""),
            "peer_id": it.get("peer_id"),
            "title": it.get("title"),
            "subscribers": subs,
            "er": s.get("er"),
            "is_scam": it.get("is_scam"),
            "sanctioned": it.get("is_active_any_sanction"),
            "raw": {"search": it},
        }

    def search(self, query: str) -> list[dict]:
        """Список каналов по поисковому запросу (до ~10, отсортированы по релевантности/охвату)."""
        try:
            r = self._get(_BASE + "/search?query=" + quote(query))
            items = (r.json() or {}).get("items", [])
        except Exception as e:  # noqa: BLE001
            log.warning("telemetr search %r: %s", query, e)
            return []
        return [self._parse_item(it) for it in items if (it.get("links") or {}).get("userName")]

    def _enrich(self, base: dict) -> None:
        """Best-effort деталь (quality / накрутка / рост / цена) по совпадению peer_id."""
        title = base.get("title") or base.get("username") or ""
        clean = (re.split(r"[|,\-—:•/]", title)[0].strip() or title)[:40]
        if not clean:
            return
        try:
            r = self._get(_BASE + "?page=1&per_page=25&title=" + quote(clean))
            for it in (r.json() or {}).get("items", []):
                if it.get("peer_id") == base.get("peer_id"):
                    q = it.get("quality", {}) or {}
                    sa = it.get("sanctions", {}) or {}
                    lang = it.get("language") or {}
                    base.update({
                        "quality_score": q.get("quality"),
                        "premium_subs": q.get("premium_subs"),
                        "month_growth": q.get("subscribers_month_growth"),
                        "ad_price": it.get("advertisement_price"),
                        "language": lang.get("code"),
                        "is_verified": it.get("is_verified"),
                        "is_boosting": sa.get("is_boosting"),
                        "is_stolen": sa.get("is_stolen"),
                        "is_scam": sa.get("is_scam", base.get("is_scam")),
                    })
                    base["raw"]["detail"] = it
                    break
        except Exception as e:  # noqa: BLE001 — деталь опциональна
            log.warning("telemetr detail %s: %s", base.get("username"), e)

    def fetch(self, username: str) -> dict:
        """Снять статистику одного канала по username (для регулярного обновления targets)."""
        u = username.lstrip("@")
        items = self.search(u)
        base = next((it for it in items if it["username"].lower() == u.lower()), None)
        if base is None:
            return {"source": self.SOURCE, "username": u, "error": "not_found_on_telemetr"}
        self._enrich(base)
        return base
