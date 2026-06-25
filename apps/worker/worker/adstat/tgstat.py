"""TGStat — клиент (HTML-парсинг через curl_cffi).

TGStat за Cloudflare: нужен валидный cf_clearance, привязанный к IP+UA и протухающий за часы.
На сервере IP другой, чем у браузера, где экспортировали куки → clearance не подойдёт и прилетит
challenge. Поэтому источник по умолчанию выключен (ADSTAT_TGSTAT_ENABLED=false); включать только
когда на серверном IP добыт свежий clearance (FlareSolverr / CF-Clearance-Scraper). См. README.

Отдаёт: подписчики (+дельты), средний охват, ERR, индекс цитирования, категория, гео.
"""
from __future__ import annotations

import re

from curl_cffi import requests as creq

from apps.worker.worker.adstat.cookies import load_netscape_cookies


def _tokens(html: str) -> list[str]:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html)
    html = re.sub(r"<[^>]+>", "\n", html)
    html = html.replace(" ", " ").replace("&nbsp;", " ")
    return [ln.strip() for ln in html.split("\n") if ln.strip()]


def _num(s: str | None) -> int | None:
    s = re.sub(r"[^\d-]", "", s or "")
    return int(s) if s and s != "-" else None


def _pct(s: str | None) -> float | None:
    if not s:
        return None
    m = re.search(r"[\d.,]+", s.replace(",", "."))
    return float(m.group()) if m else None


def _idx(toks: list[str], label: str) -> int:
    for i, t in enumerate(toks):
        if t == label:
            return i
    return -1


def parse_tgstat(html: str) -> dict:
    t = _tokens(html)
    d: dict = {}
    i = _idx(t, "сегодня")
    if i >= 2:
        d["subscribers"] = _num(t[i - 2])
        d["delta_today"] = _num(t[i - 1])
    for label, key in (("за неделю", "delta_week"), ("за месяц", "delta_month"),
                       ("упоминаний", "mentions"), ("уп. каналов", "citing_channels"),
                       ("репостов", "reposts")):
        i = _idx(t, label)
        if i > 0:
            d[key] = _num(t[i - 1])
    i = _idx(t, "ERR")
    if i >= 2:
        d["err"] = _pct(t[i - 1])
        d["avg_reach"] = _num(t[i - 2])
    i = _idx(t, "Категория:")
    if i >= 0 and i + 1 < len(t):
        d["category"] = t[i + 1]
    i = _idx(t, "Гео и язык канала:")
    if i >= 0 and i + 1 < len(t):
        d["geo"] = t[i + 1].rstrip(",")
    return d


class TGStatClient:
    SOURCE = "tgstat"

    def __init__(self, cookies_path: str, flaresolverr_url: str = ""):
        self._cookies = load_netscape_cookies(cookies_path, "tgstat.ru")
        self._fs = (flaresolverr_url or "").strip()

    @property
    def ready(self) -> bool:
        return bool(self._cookies.get("tgstat_sirk"))

    def _direct(self, url: str) -> tuple[str, str | None]:
        """curl_cffi напрямую — проходит только при валидном cf_clearance (локально, тот же IP)."""
        try:
            r = creq.get(url, cookies=self._cookies, impersonate="chrome", timeout=45)
            return r.text, None
        except Exception as e:  # noqa: BLE001
            return "", str(e)[:200]

    def _via_flaresolverr(self, url: str) -> tuple[str, str | None]:
        """Через FlareSolverr: реальный браузер решает Cloudflare на серверном IP, отдаёт HTML."""
        payload = {
            "cmd": "request.get", "url": url, "maxTimeout": 60000,
            "cookies": [{"name": k, "value": v, "domain": ".tgstat.ru"} for k, v in self._cookies.items()],
        }
        try:
            r = creq.post(self._fs, json=payload, timeout=90)
            j = r.json()
        except Exception as e:  # noqa: BLE001
            return "", f"flaresolverr: {e}"[:200]
        if j.get("status") != "ok":
            return "", f"flaresolverr: {str(j.get('message'))[:140]}"
        return (j.get("solution", {}) or {}).get("response", ""), None

    def fetch(self, username: str) -> dict:
        u = username.lstrip("@")
        url = f"https://tgstat.ru/channel/@{u}/stat"
        html, err = self._via_flaresolverr(url) if self._fs else self._direct(url)
        if err:
            return {"source": self.SOURCE, "username": u, "error": err}
        if "just a moment" in html.lower() or not html:
            return {"source": self.SOURCE, "username": u, "error": "cloudflare_challenge"}
        d = parse_tgstat(html)
        d.update({"source": self.SOURCE, "username": u, "raw": {"category": d.get("category"), "geo": d.get("geo")}})
        return d
