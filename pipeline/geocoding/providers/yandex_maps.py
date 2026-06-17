import json
import re
from typing import Final

import httpx


class YandexMapsScraper:
    SEARCH_URLS: Final[tuple[str, ...]] = ("https://yandex.ru/maps/", "https://yandex.com/maps/")
    USER_AGENT: Final[str] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    # Coordinates of the FIRST business result. In Yandex's embedded JSON the item's
    # "coordinates":[lon,lat] precedes its "type":"business", so we match the coords
    # block immediately followed (no other coords between) by a business marker.
    _BIZ_COORDS_RE: Final[re.Pattern] = re.compile(
        r'"coordinates":\[(?P<lon>-?\d+\.\d+),(?P<lat>-?\d+\.\d+)\]'
        r'(?:(?!"coordinates":\[).)*?"type":"business"',
        re.DOTALL,
    )
    # Sanity bounds (Russia) to reject a stray/viewport coordinate.
    _LAT_RANGE: Final[tuple[float, float]] = (41.0, 82.0)
    _LON_RANGE: Final[tuple[float, float]] = (19.0, 190.0)

    @staticmethod
    def extract_first_business_coords(html: str) -> tuple[float, float] | None:
        if not html:
            return None
        match = YandexMapsScraper._BIZ_COORDS_RE.search(html)
        if not match:
            return None
        lat = float(match.group("lat"))
        lon = float(match.group("lon"))
        lat_lo, lat_hi = YandexMapsScraper._LAT_RANGE
        lon_lo, lon_hi = YandexMapsScraper._LON_RANGE
        if not (lat_lo <= lat <= lat_hi and lon_lo <= lon <= lon_hi):
            return None
        return lat, lon

    async def geocode(self, query: str, city_hint: str | None = None) -> tuple[float, float, str] | None:
        """Keyless geocode via Yandex Maps search → (lat, lon, address) of the first business.

        Accurate for RU addresses/venue names. Returns None on captcha/miss so the
        caller can fall back. NOTE: scrapes Yandex Maps — for production volume prefer
        the official Yandex Geocoder API (set YANDEX_GEOCODER_KEY).
        """
        text = (query or "").strip()
        if not text:
            return None
        search_text = f"{text} {city_hint}".strip() if city_hint else text
        params = {"text": search_text}
        headers = {"User-Agent": self.USER_AGENT, "Accept-Language": "ru,en;q=0.9"}
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
                for url in self.SEARCH_URLS:
                    response = await client.get(url, params=params, headers=headers)
                    if response.status_code >= 400 or not response.text or self._is_captcha_page(response.text):
                        continue
                    coords = self.extract_first_business_coords(response.text)
                    if coords:
                        address = self.extract_first_business_address(response.text) or ""
                        return coords[0], coords[1], address
        except httpx.HTTPError:
            return None
        return None

    async def find_address_by_place(self, venue_name: str, city_hint: str | None = None) -> str | None:
        addresses = await self.find_addresses_by_place(venue_name=venue_name, city_hint=city_hint, limit=1)
        return addresses[0] if addresses else None

    async def find_addresses_by_place(
        self,
        venue_name: str,
        city_hint: str | None = None,
        limit: int = 5,
    ) -> list[str]:
        place = (venue_name or "").strip()
        if not place:
            return []

        query = f"{place} {city_hint}".strip() if city_hint else place
        params = {"text": query}
        headers = {"User-Agent": self.USER_AGENT, "Accept-Language": "ru,en;q=0.9"}

        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
                for url in self.SEARCH_URLS:
                    response = await client.get(url, params=params, headers=headers)
                    if response.status_code >= 400 or not response.text or self._is_captcha_page(response.text):
                        continue
                    addresses = self.extract_business_addresses(response.text, limit=limit)
                    if addresses:
                        return addresses
        except httpx.HTTPError:
            return []
        return []

    @staticmethod
    def extract_first_business_address(html: str) -> str | None:
        addresses = YandexMapsScraper.extract_business_addresses(html, limit=1)
        return addresses[0] if addresses else None

    @staticmethod
    def extract_business_addresses(html: str, limit: int = 5) -> list[str]:
        if not html:
            return []

        pattern = re.compile(
            r'"type":"business".{0,2000}?"address":"(?P<address>(?:\\.|[^"\\]){4,500})"',
            flags=re.DOTALL,
        )
        addresses: list[str] = []
        seen: set[str] = set()
        safe_limit = max(1, limit)
        for match in pattern.finditer(html):
            raw_address = match.group("address")
            try:
                address = json.loads(f'"{raw_address}"')
            except json.JSONDecodeError:
                continue
            normalized = str(address).strip()
            if not normalized or normalized in seen:
                continue
            addresses.append(normalized)
            seen.add(normalized)
            if len(addresses) >= safe_limit:
                break
        return addresses

    @staticmethod
    def _balanced_array(html: str, key: str) -> object | None:
        """Slice the JSON array that follows `key` (e.g. '"workingTime":'),
        balancing brackets so nested objects/arrays are captured, then parse it."""
        idx = html.find(key)
        if idx < 0:
            return None
        start = html.find("[", idx)
        if start < 0:
            return None
        depth = 0
        for i in range(start, min(len(html), start + 5000)):
            c = html[i]
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[start : i + 1])
                    except (json.JSONDecodeError, ValueError):
                        return None
        return None

    @staticmethod
    def extract_working_hours(html: str) -> dict | None:
        """Working hours of the first business — Yandex embeds a structured
        `workingTime` array (index 0=Sunday … 6=Saturday, matching JS getDay)
        plus a human `workingTimeText`. Returns {text, week} where week[d] is a
        list of ["HH:MM","HH:MM"] ranges or None (closed)."""
        if not html:
            return None
        arr = YandexMapsScraper._balanced_array(html, '"workingTime":')
        text_m = re.search(r'"workingTimeText":"([^"]{0,160})"', html)
        text = ""
        if text_m:
            try:
                text = json.loads(f'"{text_m.group(1)}"').strip()
            except json.JSONDecodeError:
                text = text_m.group(1)
        week: list | None = None
        if isinstance(arr, list) and len(arr) == 7:
            week = []
            for day in arr:
                if not isinstance(day, list) or not day:
                    week.append(None)
                    continue
                ranges: list[list[str]] = []
                for iv in day:
                    if not isinstance(iv, dict):
                        continue
                    f, t = iv.get("from") or {}, iv.get("to") or {}
                    fh, fm = f.get("hours"), f.get("minutes")
                    th, tm = t.get("hours"), t.get("minutes")
                    if fh is None or th is None:
                        continue
                    fm, tm = fm or 0, tm or 0
                    if fh == th and fm == tm:
                        fh, fm, th, tm = 0, 0, 24, 0  # from == to → round-the-clock
                    elif th == 0 and tm == 0:
                        th = 24  # closes at midnight → 24:00
                    ranges.append([f"{fh:02d}:{fm:02d}", f"{th:02d}:{tm:02d}"])
                week.append(ranges or None)
        if not week and not text:
            return None
        return {"text": text, "week": week}

    async def fetch_hours(self, query: str, city_hint: str | None = None) -> dict | None:
        """Keyless working hours for a venue name → {hours:{text,week}, coords}.
        Source-agnostic: any venue (any event source) resolves the same way.

        Tri-state so callers can tell a BLOCK from a genuine miss:
          • {"hours": …, "coords": …} — found.
          • None — reached Yandex, the business simply lists no hours.
          • {"blocked": True} — every endpoint captcha'd / errored, i.e. we never got
            a clean answer. The caller MUST NOT cache this as "no hours" (see H3)."""
        text = (query or "").strip()
        if not text:
            return None
        params = {"text": f"{text} {city_hint}".strip() if city_hint else text}
        headers = {"User-Agent": self.USER_AGENT, "Accept-Language": "ru,en;q=0.9"}
        reached = False  # got a real (non-captcha, <400) page from at least one endpoint
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
                for url in self.SEARCH_URLS:
                    response = await client.get(url, params=params, headers=headers)
                    if response.status_code >= 400 or not response.text or self._is_captcha_page(response.text):
                        continue
                    reached = True
                    hours = self.extract_working_hours(response.text)
                    if hours:
                        return {"hours": hours, "coords": self.extract_first_business_coords(response.text)}
        except httpx.HTTPError:
            return {"blocked": True}  # network/timeout — transient, not "no hours"
        if not reached:
            return {"blocked": True}  # every endpoint captcha'd/errored — transient block
        return None  # reached Yandex; the business genuinely lists no hours

    @staticmethod
    def _is_captcha_page(html: str) -> bool:
        lowered = html.casefold()
        return "are you not a robot?" in lowered or "checkcaptcha" in lowered or "smartcaptcha" in lowered
