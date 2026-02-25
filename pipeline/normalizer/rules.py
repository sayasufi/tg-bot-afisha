from datetime import datetime, timezone

from pipeline.normalizer.extractors import NormalizedCandidate, parse_age, parse_dates, parse_price


def _parse_kudago_dates(payload: dict) -> tuple[datetime | None, datetime | None]:
    dates = payload.get("dates")
    if not isinstance(dates, list) or not dates:
        return None, None
    first = dates[0] if isinstance(dates[0], dict) else {}
    start = first.get("start")
    end = first.get("end")
    start_dt = datetime.fromtimestamp(int(start), tz=timezone.utc) if start else None
    end_dt = datetime.fromtimestamp(int(end), tz=timezone.utc) if end else None
    return start_dt, end_dt


def _parse_ldjson_dates(payload: dict) -> tuple[datetime | None, datetime | None]:
    start_raw = payload.get("startDate")
    end_raw = payload.get("endDate")
    start_dt = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00")) if start_raw else None
    end_dt = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00")) if end_raw else None
    return start_dt, end_dt


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

        price_text = str(payload.get("price") or "")
        price_min, price_max = parse_price(f"{raw_text} {description} {price_text}")
        if payload.get("is_free") is True and price_min is None and price_max is None:
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
