import asyncio
import hashlib
import html
import re
from datetime import datetime, timedelta, timezone

import httpx

from connectors.base import RawRecord
from core.config.settings import get_settings

_MSK = timezone(timedelta(hours=3))


class TimepadConnector:
    """Timepad (api.timepad.ru) — independent-organiser events the big aggregators under-cover:
    galleries, chamber concerts, arthouse/festival cinema, immersive theatre. Timepad is organiser-
    driven and noisy, so this connector is HEAVILY CURATED, not a firehose:

      * category WHITELIST — only the cultural buckets (theatre/cinema/concerts/exhibitions/art/hobby).
        Excursion-quest mills, sport and the vague "other" buckets are left out.
      * recurrence COLLAPSE — Timepad posts the SAME event once per date (a x3-9 inflation, e.g. one
        exhibition listed 134 times). We group by (organiser + base title) and emit ONE event with a
        start..end run, not 134 copies.
      * junk + spam filters — gift certificates, B2B consultations, placeless events (no street
        address, e.g. roaming quest-walks) and known quest-mill organisers are dropped outright.

    Prices come from registration_data.price_min/max, which the LIST endpoint already returns — so no
    per-event detail calls. Timepad exposes no coordinates, so the street address drives geocoding
    downstream; that's also why a missing address disqualifies an event (it couldn't be mapped).
    """

    source_name = "timepad"

    # Curated cultural whitelist — Timepad category NAMES, resolved to ids at fetch time. Note: "Хобби и
    # творчество" is intentionally OUT — it's commercial master-class mills (lectures), which the owner
    # doesn't want; the few lectures that still slip in via "Искусство и культура" are dropped at dedup.
    _WHITELIST = ("Театры", "Кино", "Концерты", "Выставки", "Искусство и культура")
    # Timed categories: a concrete single date+time (the next session), NOT a multi-day range.
    _TIMED = {"театры", "кино", "концерты"}
    # Run categories: an all-day open..close span (an exhibition), no spurious opening clock.
    _RUN = {"выставки"}
    # Organisers that flood the feed with near-identical commercial listings — dropped wholesale.
    _ORG_BLOCK = ("gistoria", "гистория", "шаговед", "quest4walk", "квесты для прогулок", "мой спортивный район")
    # Titles that aren't real events (gift cards, B2B consults) or are lectures/workshops (owner: no lectures).
    _TITLE_BLOCK = ("подарочный сертификат", "сертификат на", "подарочная карта", "консультация", "абонемент",
                    "лекция", "лекторий", "мастер-класс", "мастер класс", "семинар", "воркшоп")
    _PAGE = 100
    _MAX_PAGES = 60
    _PAGE_CONCURRENCY = 6  # skip-pages are independent → fetch a batch at a time

    def __init__(self, city: str = "Москва", lookahead_days: int = 180) -> None:
        self.settings = get_settings()
        self.city = city
        self.lookahead_days = lookahead_days

    # ---- pure helpers (unit-tested without HTTP) ----
    @staticmethod
    def _clean(text: object) -> str:
        s = html.unescape(str(text or "")).replace("�", "").strip()
        return re.sub(r"\s+", " ", s)

    @classmethod
    def _base_title(cls, name: object) -> str:
        """Title stripped to its recurring core (no dates/numbers/punctuation) — the collapse key."""
        s = cls._clean(name).lower()
        s = re.sub(r"\(.*?\)", " ", s)        # drop parentheticals: "(без гида)", "(22-26 июня)"
        s = re.sub(r"[0-9]+", " ", s)          # drop numbers / dates
        s = re.sub(r"[^а-яёa-z ]+", " ", s)     # punctuation / latin-symbol noise
        return re.sub(r"\s+", " ", s).strip()[:60]

    @staticmethod
    def _price_text(reg: object) -> str:
        """registration_data → a price string parse_price_field round-trips exactly. ONLY a POSITIVE price
        is trustworthy: Timepad reports price 0/0 both for genuinely-free events AND for paid ones whose
        tickets are external / registration is closed (camps, media-accreditation, business clubs). So
        0/0 (or missing) → "" (UNKNOWN, no price shown) — never a false «бесплатно»."""
        if not isinstance(reg, dict):
            return ""
        lo = reg.get("price_min"); hi = reg.get("price_max")
        lo = float(lo) if isinstance(lo, (int, float)) and lo > 0 else None
        hi = float(hi) if isinstance(hi, (int, float)) and hi > 0 else None
        if lo and hi and hi > lo:
            return f"от {int(lo)} до {int(hi)} рублей"
        if lo and hi and lo == hi:
            return f"{int(lo)} рублей"
        if lo:
            return f"от {int(lo)} рублей"
        if hi:
            return f"до {int(hi)} рублей"
        return ""

    @classmethod
    def _is_junk(cls, e: dict) -> bool:
        if (e.get("moderation_status") or "shown") != "shown":
            return True
        if not str((e.get("location") or {}).get("address") or "").strip():
            return True  # placeless (roaming quest-walks) — can't be put on the map
        name = cls._clean(e.get("name")).lower()
        if not name or any(b in name for b in cls._TITLE_BLOCK):
            return True
        org = cls._clean((e.get("organization") or {}).get("name")).lower()
        return any(b in org for b in cls._ORG_BLOCK)

    @staticmethod
    def _parse_dt(v: object) -> datetime | None:
        if not v:
            return None
        try:
            return datetime.fromisoformat(str(v))
        except ValueError:
            return None

    def build_records(self, events: list[dict]) -> list[RawRecord]:
        """Filter junk → group by (organiser, base title) → ONE RawRecord per distinct event with a
        start..end run. Pure (no I/O): takes raw Timepad event dicts, returns normaliser-shaped records."""
        now = datetime.now(_MSK)
        until = now + timedelta(days=self.lookahead_days)
        groups: dict[tuple, list[dict]] = {}
        for e in events:
            if self._is_junk(e):
                continue
            start = self._parse_dt(e.get("starts_at"))
            if start is None or start > until:
                continue
            key = ((e.get("organization") or {}).get("id"), self._base_title(e.get("name")))
            groups.setdefault(key, []).append({**e, "_start": start})

        records: list[RawRecord] = []
        for (org_id, base), grp in groups.items():
            grp.sort(key=lambda x: x["_start"])
            future = [g for g in grp if g["_start"] >= now]
            if not future:
                continue  # never surface a past-only event — no last-year leakage
            rep = future[0]                              # soonest UPCOMING session
            start = rep["_start"]
            rep_end = self._parse_dt(rep.get("ends_at"))
            ends = [d for d in (self._parse_dt(g.get("ends_at")) for g in grp) if d]
            run_end = max(ends) if ends else None
            cats = [self._clean(c.get("name")) for c in (rep.get("categories") or []) if c.get("name")]
            low = {c.lower() for c in cats}
            multiday = bool(run_end and run_end.date() > start.date())
            # Timed (theatre/cinema/concert, or any single-day event): a CONCRETE next session — keep its
            # clock, end only if same day. NOT a multi-day range (that misread discrete shows as a "run").
            # Run (exhibition / genuine multi-day span): ALL-DAY open..close, dropping the spurious opening
            # clock so the card reads "по <дата>" instead of a confusing time.
            if (low & self._TIMED) or (not (low & self._RUN) and not multiday):
                date_start = start
                date_end = rep_end if (rep_end and rep_end.date() == start.date()) else None
            else:
                date_start = start.replace(hour=0, minute=0, second=0, microsecond=0)
                date_end = run_end.replace(hour=0, minute=0, second=0, microsecond=0) if multiday else None
            loc = rep.get("location") or {}
            org_name = self._clean((rep.get("organization") or {}).get("name"))
            poster = rep.get("poster_image")
            age = str(rep.get("age_limit") or "").strip()
            payload = {
                "name": self._clean(rep.get("name")),
                "description_short": self._clean(rep.get("description_short")),
                "startDate": date_start.isoformat(),
                "endDate": date_end.isoformat() if date_end else None,
                "place": {"title": org_name, "address": self._clean(loc.get("address"))},
                "price": self._price_text(rep.get("registration_data")),
                "age_restriction": int(age) if age.isdigit() else None,
                "categories": cats,
                "poster_image": poster.get("default_url") if isinstance(poster, dict) else None,
                "site_url": rep.get("url"),
                "sessions": len(grp),
                "iso_dates": True,  # startDate/endDate ARE the authoritative session → drives occurrence upsert + prune
                # registration_data IS the price truth: absent → UNKNOWN, not free. Without this the
                # normalizer scans the description and a stray «бесплатная регистрация/парковка» mislabels
                # half the catalog as free. Suppress that text fallback (paid events still carry a price).
                "price_authoritative": True,
            }
            if not payload["name"]:
                continue
            ext_id = "tp-" + hashlib.sha256(f"{org_id}|{base}".encode()).hexdigest()[:16]
            # Include the date in raw_text → content_hash tracks it. The collapse key (org+title) is
            # stable, so without this a shifted "soonest session" (the prior one passed) would never
            # re-normalize — the event would freeze on a past date and get expired despite future sessions.
            date_token = date_start.date().isoformat() + ("/" + date_end.date().isoformat() if date_end else "")
            raw_text = " ".join([payload["name"], payload["description_short"], org_name,
                                 payload["place"]["address"], date_token]).strip()
            records.append(RawRecord(external_id=ext_id, payload=payload, raw_text=raw_text))
        return records

    async def _category_ids(self, client: httpx.AsyncClient) -> list[str]:
        """Resolve whitelist category NAMES → ids via the Timepad dictionary (ids aren't stable enough
        to hardcode). Empty list on failure → fetch() yields nothing rather than an unfiltered firehose."""
        try:
            r = await client.get(f"{self.settings.timepad_base_url}/dictionary/event_categories")
            data = r.json()
            rows = data.get("values") if isinstance(data, dict) else data
            name2id = {self._clean(x.get("name")): x.get("id") for x in (rows or []) if isinstance(x, dict) and x.get("id")}
        except Exception:
            return []
        return [str(name2id[n]) for n in self._WHITELIST if name2id.get(n)]

    async def fetch(self, cursor: str | None = None) -> tuple[list[RawRecord], str | None]:
        token = self.settings.timepad_token
        if not token:
            return [], None
        now = datetime.now(_MSK)
        until = now + timedelta(days=self.lookahead_days)
        headers = {"Authorization": f"Bearer {token}", "User-Agent": "tg-bot-afisha/0.1"}
        fields = ("id,name,starts_at,ends_at,location,categories,organization,age_limit,"
                  "poster_image,description_short,url,registration_data,moderation_status")
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=20.0, pool=20.0)
        events: list[dict] = []
        # SSRF guard: don't follow redirects into internal space.
        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=False) as client:
            ids = await self._category_ids(client)
            if not ids:
                return [], None
            base = f"{self.settings.timepad_base_url}/events"
            common = {
                "cities": self.city,
                "starts_at_min": now.date().isoformat(),
                "starts_at_max": until.date().isoformat(),
                "category_ids": ",".join(ids),
                "fields": fields,
                "sort": "+starts_at",
                "limit": self._PAGE,
            }
            # skip-offset pages are independent → fetch them in CONCURRENT batches, stopping once a
            # short page appears (= the last page). build_records is future-only, so over-fetching a
            # little past the window is harmless. ~6× faster than page-by-page.
            sem = asyncio.Semaphore(self._PAGE_CONCURRENCY)

            async def _page(p: int) -> list[dict]:
                async with sem:
                    resp = await client.get(base, params={**common, "skip": p * self._PAGE})
                    resp.raise_for_status()
                    return resp.json().get("values") or []

            done = False
            start = 0
            while start < self._MAX_PAGES and not done:
                batch = range(start, min(start + self._PAGE_CONCURRENCY, self._MAX_PAGES))
                for vals in await asyncio.gather(*(_page(p) for p in batch)):
                    events.extend(vals)
                    if len(vals) < self._PAGE:
                        done = True  # a short page is the last page
                start += self._PAGE_CONCURRENCY
        return self.build_records(events), None
