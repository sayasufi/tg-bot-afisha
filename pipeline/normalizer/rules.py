from datetime import datetime, timedelta, timezone

import dateparser

from pipeline.normalizer.extractors import NormalizedCandidate, parse_age, parse_dates, parse_price, parse_price_field


def _safe_ts_to_dt(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    # KudaGo may return sentinel negative timestamps (year 0001).
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _has_clock(row: dict) -> bool:
    """True if the KudaGo date row carries a real start time (not an all-day
    placeholder). KudaGo emits a 00:00:00 / null `start_time` for all-day or
    long-run rows, and a real one (e.g. 19:00:00) for actual sessions."""
    st = row.get("start_time")
    return bool(st) and str(st) != "00:00:00"


def _parse_kudago_dates(payload: dict) -> tuple[datetime | None, datetime | None]:
    dates = payload.get("dates")
    if not isinstance(dates, list) or not dates:
        return None, None

    now = datetime.now(timezone.utc)
    # Must match the occurrence-lookahead window (_OCCURRENCE_LOOKAHEAD_DAYS = 365 in
    # core.db.repositories.ingestion) and the KudaGo connector's _LOOKAHEAD_DAYS (365).
    # A 30-day gate here silently dropped KudaGo sessions the connector fetched 31..365
    # days out (a play's autumn run never reached the map).
    until = now + timedelta(days=365)
    upcoming: list[tuple[datetime, datetime | None, bool]] = []  # (start, end, has_clock)
    ongoing: tuple[datetime, datetime | None] | None = None
    for row in dates:
        if not isinstance(row, dict):
            continue
        start_dt = _safe_ts_to_dt(row.get("start"))
        end_dt = _safe_ts_to_dt(row.get("end"))
        if start_dt and now <= start_dt <= until:
            upcoming.append((start_dt, end_dt, _has_clock(row)))
        # Started before the window but still running (e.g. an exhibition): keep the REAL
        # start + end so the UI can show it as a run ("по 1 января"), not start==end.
        elif start_dt and end_dt and start_dt < now <= end_dt and ongoing is None:
            ongoing = (start_dt, end_dt)

    if upcoming:
        # Prefer the soonest session that has a real clock time over an all-day /
        # midnight placeholder row — many KudaGo events list both, and picking the
        # placeholder is what made timed events look like they run 24/7.
        timed = [u for u in upcoming if u[2]]
        chosen = min(timed or upcoming, key=lambda u: u[0])
        return chosen[0], chosen[1]

    if ongoing:
        return ongoing
    return None, None


def _parse_flexible_dt(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        # LLM extraction occasionally returns natural-language dates ("15 июня 2026")
        # despite being asked for ISO-8601; a parse failure must not kill the batch.
        return dateparser.parse(
            text,
            languages=["ru", "en"],
            settings={"TIMEZONE": "Europe/Moscow", "RETURN_AS_TIMEZONE_AWARE": True},
        )


def _parse_ldjson_dates(payload: dict) -> tuple[datetime | None, datetime | None]:
    return _parse_flexible_dt(payload.get("startDate")), _parse_flexible_dt(payload.get("endDate"))


def _extract_images(payload: dict) -> list[str]:
    images: list[str] = []
    poster = payload.get("poster_image")
    if poster:
        images.append(str(poster))

    source_images = payload.get("images")
    if isinstance(source_images, list):
        for row in source_images:
            if isinstance(row, dict):
                url = row.get("image") or row.get("url")
                if url:
                    images.append(str(url))
            elif isinstance(row, str):
                images.append(row)

    if isinstance(payload.get("image"), str):
        images.append(str(payload["image"]))

    uniq = []
    seen = set()
    for img in images:
        if img in seen:
            continue
        seen.add(img)
        uniq.append(img)
    return uniq


def _extract_venue(payload: dict) -> tuple[str, str]:
    place = payload.get("place") if isinstance(payload.get("place"), dict) else {}
    if place:
        venue = str(place.get("title") or place.get("name") or "")
        address = str(place.get("address") or "")
        return venue, address

    location = payload.get("location") if isinstance(payload.get("location"), dict) else {}
    if location:
        venue = str(location.get("name") or "")
        address = str(location.get("address") or "")
        return venue, address

    return str(payload.get("venue") or ""), str(payload.get("address") or payload.get("location") or "")


class RuleBasedNormalizer:
    def normalize(self, payload: dict, raw_text: str) -> list[NormalizedCandidate]:
        title = payload.get("name") or payload.get("title") or payload.get("short_title") or raw_text.split("\n")[0][:200] or "Untitled"
        description = payload.get("description_short") or payload.get("description") or payload.get("body_text") or raw_text

        date_start = date_end = None
        if isinstance(payload.get("dates"), list):
            date_start, date_end = _parse_kudago_dates(payload)
        elif payload.get("startDate") or payload.get("endDate"):
            date_start, date_end = _parse_ldjson_dates(payload)
        if not date_start:
            date_start, date_end = parse_dates(raw_text)

        venue, address = _extract_venue(payload)

        # Prefer the source's dedicated price field (trusted), then fall back to
        # currency-anchored numbers in the free text; never scan raw digits
        # (addresses/phones/years would poison it).
        price_text = str(payload.get("price") or "")
        price_min, price_max = parse_price_field(price_text)
        # `price_authoritative` sources (Timepad) put the WHOLE price in `price`; absence means UNKNOWN,
        # so don't scrape the description — a stray «бесплатная регистрация/парковка» would mislabel a
        # paid event as free. Other sources keep the free-text fallback (Telegram, etc.).
        if price_min is None and price_max is None and not payload.get("price_authoritative"):
            price_min, price_max = parse_price(f"{description} {raw_text}")
        if payload.get("is_free") is True and not price_min and not price_max:
            price_min, price_max = 0.0, 0.0

        age_raw = payload.get("age_restriction")
        if isinstance(age_raw, int):
            age_limit = f"{age_raw}+"
        else:
            age_limit = str(age_raw or "") or parse_age(raw_text)

        source_url = payload.get("site_url") or payload.get("url") or payload.get("link") or ""
        images = _extract_images(payload)

        tags: list[str] = []
        for key in ("categories", "tags"):
            values = payload.get(key)
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict) and item.get("slug"):
                        tags.append(str(item["slug"]))
                    elif isinstance(item, str):
                        tags.append(item)

        confidence = 0.85 if title and date_start else 0.6
        candidate = NormalizedCandidate(
            title=title,
            description=description,
            date_start=date_start,
            date_end=date_end,
            venue=venue,
            address=address,
            price_min=price_min,
            price_max=price_max,
            currency="RUB",
            age_limit=age_limit,
            tags=list(dict.fromkeys(tags)),
            images=images,
            source_url=str(source_url),
            parse_confidence=confidence,
        )
        return [candidate]
