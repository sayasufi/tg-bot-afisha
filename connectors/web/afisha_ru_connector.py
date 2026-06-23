import asyncio
import html as html_lib
import json
import random
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import HTTPError

from connectors.base import RawRecord

# afisha.ru's edge fingerprints the TLS handshake and 403s plain Python clients;
# curl_cffi impersonates a real Chrome handshake, which the edge accepts (same
# trick as the Yandex Afisha connector).
_IMPERSONATE = "chrome"

# Moscow is a fixed UTC+3 (no DST since 2014) — a plain offset avoids depending
# on tzdata being installed.
_MSK = timezone(timedelta(hours=3))
_LOOKAHEAD_DAYS = 365  # match the occurrence window; afisha lists ~a year ahead
_DATES_CAP = 12  # max discrete dates per event (a play's near-term run; not exhibitions)

# afisha.ru serves no public JSON listing API (the web GraphQL is a persisted-
# query allowlist; the mobile API signs requests). But every /<city>/schedule_*/
# page server-renders its full event list into `window.__nrp.root.model`, which
# we read directly. Each rubric is (url path, our-category hint). "standup" is a
# concert sub-filter; afisha "kids" is films, so it's intentionally excluded.
_DEFAULT_RUBRICS: list[tuple[str, str]] = [
    ("schedule_concert", "concert"),
    ("schedule_theatre", "theatre"),
    ("schedule_exhibition", "exhibition"),
    ("schedule_concert/standup", "standup"),
]

_ROOT_RE = re.compile(r"\['root'\]\s*=\s*")

# Exact session dates come from afisha's GraphQL API (graph.afisha.ru) — the SAME
# data the detail page's schedule tab renders, but as light JSON (~1-2 KB), with no
# anti-bot challenge, and reachable straight from a datacenter IP. www.afisha.ru
# serves a captcha to cloud IPs (hence the listing crawl's TLS impersonation), but
# the API does not. One call per event returns every session (date/time/place), so
# a multi-show run or a touring concert comes back in full at once — no per-event
# HTML fetch, no hammering. Operations are content-type specific; the persisted-
# query hash is pinned per operation and matches the live site. If afisha
# re-versions a query the hash 404s ("PersistedQueryNotFound") and we fall back to
# the listing Min/Max — refresh the hash from the site's Network tab if that starts.
_GRAPHQL_URL = "https://graph.afisha.ru/graphql"
# url-path segment -> (operationName, persisted sha256, global-id type prefix, extra vars)
_SCHED_OPS: dict[str, tuple[str, str, str, dict]] = {
    "performance": ("PerformanceSchedule", "4618305c1597e017f91c42e11c827ec4b95e2a839b18b76854344445c0e6722e", "Performance", {}),
    "concert": ("ConcertSchedule", "de158ba260e7085dea19ff9d62b14a2a1bea7c7fdb42ad6aa1d508c445fedfe7", "Concert", {"strategyType": "PREFER_CURRENT_CITY"}),
}
_AFISHA_CITY_ID = "2"  # Москва (City_2). Concert schedules span many cities; keep only this one.
_URL_ID_RE = re.compile(r"afisha\.ru/([a-z_]+)/[^/?#]*?(\d+)/?(?:[?#]|$)")


class AfishaRuConnector:
    """Pulls events from afisha.ru by reading the server-rendered listing model.

    Shape mirrors the other web connectors: ``async fetch(cursor) -> (records,
    next_cursor)`` plus ``async scan() -> (records, pages, stop_reason)``. The
    payloads use the same KudaGo-style keys (``dates`` as unix rows, ``place``
    with name/address/coords, ``price`` as RU text, ``categories``/``tags`` hint
    lists) so they flow through the existing normalizer -> enrich -> dedup
    pipeline unchanged.

    No auth: the pages are public HTML; we only need the Chrome TLS impersonation.
    """

    source_name = "afisha_ru"
    _PAGE_SIZE = 24  # afisha's fixed listing page size
    # afisha's nginx rate-limits server IPs and penalises bursts, so the crawl is
    # deliberately slow: a jittered multi-second gap between pages, and the daily
    # full scan is the only multi-page caller. The 5-min incremental fetches a
    # single page and just skips a tick if throttled.
    _PAGE_DELAY = 2.5  # base pause between scan pages (+ jitter)
    _PAGE_JITTER = 1.5
    _RETRY_ATTEMPTS = 3
    _RETRY_BACKOFF = 5.0  # seconds, doubled each retry on 429/5xx

    def __init__(self, city: str = "msk", rubrics: list[tuple[str, str]] | None = None, proxy: str | None = None) -> None:
        self.city = city
        self.rubrics = rubrics or _DEFAULT_RUBRICS
        # afisha blocks cloud IPs; a residential proxy makes the crawl work in prod.
        self._proxies = {"http": proxy, "https": proxy} if proxy else None

    def _session(self) -> AsyncSession:
        return AsyncSession(impersonate=_IMPERSONATE, proxies=self._proxies)

    # --- HTTP plumbing -----------------------------------------------------

    def _page_url(self, path: str, page: int) -> str:
        base = f"https://www.afisha.ru/{self.city}/{path}/"
        return base if page <= 1 else f"{base}page{page}/"

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "accept": "text/html,application/xhtml+xml",
            "accept-language": "ru-RU,ru;q=0.9",
            "referer": "https://www.afisha.ru/",
        }

    @staticmethod
    def _extract_model(html: str) -> dict:
        """Pull `window.__nrp...['root'] = {...}` out of the page HTML and return
        its `.model`. Brace-matches the object literal (string-aware) instead of a
        greedy regex so nested braces in descriptions don't truncate it."""
        m = _ROOT_RE.search(html)
        if not m:
            return {}
        start = html.find("{", m.end())
        if start < 0:
            return {}
        depth = 0
        in_str = False
        esc = False
        end = -1
        for j in range(start, len(html)):
            c = html[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        end = j + 1
                        break
        if end < 0:
            return {}
        try:
            return json.loads(html[start:end]).get("model") or {}
        except (ValueError, AttributeError):
            return {}

    async def _get(self, session: AsyncSession, url: str, attempts: int = 1):
        """GET with backoff on 429 (afisha throttles bursts) and transient 5xx.
        ``attempts=1`` (the incremental default) makes one try and raises on 429,
        so a throttled tick fails fast instead of hammering; the scan retries."""
        backoff = self._RETRY_BACKOFF
        for attempt in range(attempts):
            response = await session.get(url, headers=self._headers(), timeout=40)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == attempts - 1:
                    response.raise_for_status()
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            response.raise_for_status()
            return response
        return response  # pragma: no cover

    async def _fetch_page(self, session: AsyncSession, rubric_idx: int, page: int, today, attempts: int = 1) -> tuple[list[RawRecord], int, int]:
        """One listing page -> (records, total_pages, raw_item_count). raw_item_count
        lets a sweep tell 'empty page' (stop) from 'items present but all out of
        window' (also stop, since pages are date-sorted ascending)."""
        path, category = self.rubrics[rubric_idx]
        url = self._page_url(path, page)
        response = await self._get(session, url, attempts=attempts)
        model = self._extract_model(response.text)
        widget = model.get("ScheduleWidget") if isinstance(model.get("ScheduleWidget"), dict) else {}
        items = widget.get("Items") if isinstance(widget.get("Items"), list) else []
        pager = widget.get("Pager") if isinstance(widget.get("Pager"), dict) else {}
        total_pages = int(pager.get("PagesCount") or 1)
        records = self._build_records(items, category, today)
        return records, total_pages, len(items)

    async def fetch(self, cursor: str | None = None) -> tuple[list[RawRecord], str | None]:
        """Incremental tick: refresh the SOONEST page (page 1) of one rubric and
        advance to the next rubric. afisha sorts ascending by date, so page 1 is
        the most relevant and most-likely-to-change slice; the daily full scan
        covers the long tail. The cursor is the rubric index, cycling."""
        ri = int(cursor) % len(self.rubrics) if cursor and str(cursor).isdigit() else 0
        today = datetime.now(_MSK).date()
        records: list[RawRecord] = []
        async with self._session() as session:
            try:
                records, _, _ = await self._fetch_page(session, ri, 1, today)
            except HTTPError:
                # Throttled (or transient) — skip this tick gracefully; the cursor
                # still advances so the next tick tries the next rubric.
                records = []
        next_cursor = str((ri + 1) % len(self.rubrics))
        return records, next_cursor

    async def scan(self, max_pages: int = 60, on_page=None) -> tuple[list[RawRecord], int, str]:
        """Full in-window sweep over every rubric and page, reusing ONE session.
        ``max_pages`` is the per-rubric page cap (so a dense rubric can't starve
        the others). Stops a rubric when a page yields no in-window records
        (date-sorted feed) or the pager is exhausted. De-duplicates by external_id.

        If ``on_page`` is given it's awaited with each page's fresh records as they
        arrive, so a long scan persists incrementally — a crash keeps the pages
        already fetched instead of losing everything."""
        today = datetime.now(_MSK).date()
        all_records: list[RawRecord] = []
        seen: set[str] = set()
        pages = 0
        reasons: list[str] = []

        async with self._session() as session:
            async def _scan_rubric(ri: int) -> None:
                nonlocal pages
                page = 1
                while page <= max_pages:
                    try:
                        records, total_pages, raw_count = await self._fetch_page(session, ri, page, today, attempts=self._RETRY_ATTEMPTS)
                    except HTTPError as exc:
                        if "429" in str(exc):  # throttled — keep what we have, stop this rubric
                            reasons.append("rate_limited")
                            return
                        raise
                    pages += 1
                    # The check-and-add below has no await between statements, so concurrent rubrics
                    # can't race the shared `seen`/`all_records` (asyncio yields only at awaits).
                    fresh = []
                    for rec in records:
                        if rec.external_id not in seen:
                            seen.add(rec.external_id)
                            all_records.append(rec)
                            fresh.append(rec)
                    if on_page and fresh:
                        await on_page(fresh)
                    if raw_count == 0:
                        reasons.append("empty_page")
                        return
                    if not records:  # items present but none in window — past the horizon
                        reasons.append("out_of_window")
                        return
                    if page >= total_pages:
                        reasons.append("exhausted_rubric")
                        return
                    page += 1
                    await asyncio.sleep(self._PAGE_DELAY + random.random() * self._PAGE_JITTER)
                reasons.append("max_pages")

            # Rubrics are independent → scan them CONCURRENTLY. Pages WITHIN a rubric stay sequential
            # with the jittered delay, so this is ~rubric-count× faster WITHOUT hammering afisha's
            # anti-bot — the deliberate per-rubric throttle is preserved.
            await asyncio.gather(*(_scan_rubric(ri) for ri in range(len(self.rubrics))), return_exceptions=True)

        stop_reason = "rate_limited" if "rate_limited" in reasons else (reasons[-1] if reasons else "max_pages")
        return all_records, pages, stop_reason

    # --- record building ---------------------------------------------------

    def _build_records(self, items: list, category: str, today) -> list[RawRecord]:
        # Fast: listing fields only (Min/Max + count). The listing has no discrete
        # dates, so a sparse run yields its first/last dates here; the exact middle
        # dates are filled later by the idempotent resolve_afisha_dates job (one
        # graph.afisha.ru call per event, once) — never an extra fetch on every scan.
        records: list[RawRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            # Some rubrics wrap the data in `Tile`, others put it on the item.
            tile = item.get("Tile") if isinstance(item.get("Tile"), dict) else item
            event_id = tile.get("ID")
            title = tile.get("Name")
            if not event_id or not title:
                continue
            dates = self._build_dates(tile.get("ScheduleInfo"), tile.get("Notice"), today, is_exhibition=(category == "exhibition"))
            if not dates:
                continue  # nothing upcoming in the window
            sched = tile.get("ScheduleInfo") if isinstance(tile.get("ScheduleInfo"), dict) else {}
            price_text, is_free = self._price(tile.get("ScheduleInfo"))
            payload = {
                "id": event_id,
                "title": title,
                "description": self._strip_html(tile.get("Description")),
                "dates": dates,
                # How many sessions the listing reports — lets the resolve job tell a
                # sparse run (few discrete dates worth fetching from the detail page)
                # from a dense run (keep the listing span); 0 if unknown.
                "sessions_count": int(sched.get("SessionsCount") or 0),
                "site_url": self._abs_url(tile.get("Url")),
                "images": self._images(tile),
                # The rubric we fetched IS the category — the single authoritative
                # signal. We deliberately do NOT also emit the DisplayType
                # ("концерт"/…): the categoriser weighs every hint by a fixed
                # priority, so a stray DisplayType could override the rubric (e.g.
                # a promoted concert in the standup feed). Genres stay as tags.
                "categories": [{"slug": category}],
                "tags": self._tags(tile.get("Genres")),
                "age_restriction": tile.get("AgeRestriction") or "",
                "price": price_text,
                "is_free": is_free,
                "place": self._place(tile.get("Notice")),
            }
            records.append(RawRecord(external_id=str(event_id), payload=payload, raw_text=self._raw_text(payload)))
        return records

    def _schedule_url(self, kind: str, num: str, city_id: str) -> str | None:
        """Build the graph.afisha.ru persisted-query URL for one event's schedule."""
        op = _SCHED_OPS.get(kind)
        if not op:
            return None
        operation, sha, prefix, extra = op
        ext = json.dumps(
            {"persistedQuery": {"version": 1, "sha256Hash": sha},
             "headers": {"X-Platform": "Web", "X-Application": "Afisha", "X-Afisha-City-ID": city_id}},
            separators=(",", ":"), ensure_ascii=False,
        )
        variables = json.dumps({"id": f"{prefix}_{num}", **extra}, separators=(",", ":"), ensure_ascii=False)
        params = urllib.parse.urlencode({"extensions": ext, "operationName": operation, "variables": variables})
        return f"{_GRAPHQL_URL}?{params}"

    async def _graphql_schedule(self, session: AsyncSession, url: str, today, city_id: str = _AFISHA_CITY_ID) -> list[dict] | None:
        """Every real session date for one event, from afisha's GraphQL API. Replaces
        the listing's Min/Max span with the discrete dates (in ``city_id`` only, so a
        touring concert keeps just its Moscow shows). Returns None on any failure —
        unknown url shape, network error, re-versioned query — so the caller keeps the
        listing dates rather than wiping them."""
        m = _URL_ID_RE.search(url or "")
        if not m:
            return None
        gurl = self._schedule_url(m.group(1), m.group(2), city_id)
        if not gurl:
            return None
        try:
            response = await self._get(session, gurl, attempts=self._RETRY_ATTEMPTS)
            data = response.json()
        except (HTTPError, ValueError):
            return None
        node = ((data or {}).get("data") or {}).get(m.group(1))
        schedule = node.get("schedule") if isinstance(node, dict) else None
        if not isinstance(schedule, list):
            return None
        want_city = f"City_{city_id}" if city_id else None
        horizon = today + timedelta(days=_LOOKAHEAD_DAYS)
        rows: list[dict] = []
        seen: set[int] = set()
        for grp in schedule:
            if not isinstance(grp, dict):
                continue
            place = grp.get("place") if isinstance(grp.get("place"), dict) else {}
            pcity = (place.get("city") or {}).get("id") if isinstance(place.get("city"), dict) else None
            if want_city and pcity and pcity != want_city:
                continue  # touring show — drop sessions outside the target city
            # The schedule also carries the real venue per session, which the listing
            # often omits (→ "Unknown venue"). Surface it so the caller can place the
            # event at its actual hall instead of the city centre.
            pname = (place.get("name") or "").strip()
            paddr = ((place.get("address") or "") if isinstance(place.get("address"), str) else "").strip()
            purl = place.get("url") or ""
            for sess in grp.get("sessions") or []:
                dt = self._parse_dt(sess.get("dateTime")) if isinstance(sess, dict) else None
                if not dt or dt.date() < today or dt.date() > horizon:
                    continue
                ts = int(dt.timestamp())
                if ts in seen:
                    continue
                seen.add(ts)
                rows.append({"start": ts, "end": None, "start_date": dt.date().isoformat(),
                             "start_time": dt.strftime("%H:%M:%S"),
                             "place_name": pname, "place_address": paddr, "place_url": purl})
        rows.sort(key=lambda r: r["start"])
        return rows[:_DATES_CAP] or None

    def _build_dates(self, schedule: object, notice: object, today, is_exhibition: bool = False) -> list[dict]:
        sched = schedule if isinstance(schedule, dict) else {}
        horizon = today + timedelta(days=_LOOKAHEAD_DAYS)
        start_dt = self._parse_dt(sched.get("MinScheduleDate"))
        end_dt = self._parse_dt(sched.get("MaxScheduleDate"))

        # A continuous EXHIBITION is one open-ended run — keep it as a single span
        # ("до 30 сентября"), not a list of daily pins.
        if is_exhibition and start_dt and end_dt and (end_dt.date() - start_dt.date()) > timedelta(days=1):
            if end_dt.date() < today:
                return []
            run_start = start_dt if start_dt.date() >= today else datetime(today.year, today.month, today.day, tzinfo=_MSK)
            return [{
                "start": int(run_start.timestamp()), "end": int(end_dt.timestamp()),
                "start_date": run_start.date().isoformat(), "start_time": "00:00:00",
            }]

        # Everything else (shows, concerts) is DISCRETE — never a span, which renders
        # as a misleading range ("14 июля — 27 сентября" for 3 performances). The
        # listing only knows first/last; resolve_afisha_dates fills the middle ones
        # from the GraphQL API.
        rows: list[dict] = []
        for dt in (start_dt, end_dt):
            if not dt:
                continue
            day = dt.date()
            if day < today or day > horizon:
                continue
            ts = int(dt.timestamp())
            if any(r["start"] == ts for r in rows):
                continue
            has_time = dt.hour != 0 or dt.minute != 0
            if has_time:
                rows.append({"start": ts, "end": None, "start_date": day.isoformat(), "start_time": dt.strftime("%H:%M:%S")})
            else:
                end_ts = int(datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=_MSK).timestamp())
                rows.append({"start": ts, "end": end_ts, "start_date": day.isoformat(), "start_time": "00:00:00"})
            if len(rows) >= _DATES_CAP:
                break
        return rows

    @staticmethod
    def _price(schedule: object) -> tuple[str, bool]:
        sched = schedule if isinstance(schedule, dict) else {}
        mn = sched.get("MinPrice")
        if not isinstance(mn, (int, float)):
            return "", False
        value = int(round(mn))
        if value <= 0:
            return "Бесплатно", True
        return f"от {value} ₽", False

    @staticmethod
    def _place(notice: object) -> dict | None:
        n = notice if isinstance(notice, dict) else {}
        place = n.get("Place") if isinstance(n.get("Place"), dict) else None
        if not place:
            return None
        coords = None
        geo = n.get("GeoPoint")
        if isinstance(geo, dict):
            lat = geo.get("Latitude") or geo.get("Lat") or geo.get("latitude")
            lon = geo.get("Longitude") or geo.get("Lon") or geo.get("Lng") or geo.get("longitude")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                coords = {"lat": lat, "lon": lon}
        return {
            "id": place.get("Url"),
            "title": place.get("Name"),
            "address": place.get("Address"),
            "coords": coords,  # often None -> enrich geocodes the address
            "subway": None,
        }

    @staticmethod
    def _images(tile: dict) -> list[dict]:
        out: list[dict] = []
        for key in ("Image16x9", "Image1x1"):
            node = tile.get(key)
            if isinstance(node, dict) and node.get("Url"):
                out.append({"image": node["Url"]})
        return out

    @staticmethod
    def _tags(genres: object) -> list:
        out: list = []
        links = genres.get("Links") if isinstance(genres, dict) else None
        if isinstance(links, list):
            for tag in links[:8]:
                if not isinstance(tag, dict):
                    continue
                if tag.get("ShortName"):
                    out.append({"slug": tag["ShortName"]})
                if tag.get("Name"):
                    out.append(tag["Name"])
        return out

    @staticmethod
    def _abs_url(path: object) -> str:
        if not path:
            return ""
        text = str(path)
        return text if text.startswith("http") else f"https://www.afisha.ru{text}"

    @staticmethod
    def _strip_html(text: object) -> str:
        if not text:
            return ""
        plain = re.sub(r"<[^>]+>", " ", str(text))
        plain = html_lib.unescape(plain)
        return re.sub(r"\s+", " ", plain).strip()

    @staticmethod
    def _raw_text(payload: dict) -> str:
        place = payload.get("place") if isinstance(payload.get("place"), dict) else {}
        parts = [
            payload.get("title") or "",
            payload.get("description") or "",
            (place or {}).get("title") or "",
            (place or {}).get("address") or "",
        ]
        return " ".join(part for part in parts if part).strip()

    @staticmethod
    def _parse_dt(value: object) -> datetime | None:
        """Parse an afisha schedule datetime ('2026-06-20T14:00:00', implicitly
        Moscow). Returns an aware MSK datetime, or None."""
        if not value or "T" not in str(value):
            return None
        try:
            dt = datetime.fromisoformat(str(value)[:19])
        except ValueError:
            return None
        return dt.replace(tzinfo=_MSK) if dt.tzinfo is None else dt
