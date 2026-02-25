from pipeline.normalizer.extractors import NormalizedCandidate, parse_age, parse_dates, parse_price


class RuleBasedNormalizer:
    def normalize(self, payload: dict, raw_text: str) -> list[NormalizedCandidate]:
        title = payload.get("name") or payload.get("title") or raw_text.split("\n")[0][:200] or "Untitled"
        description = payload.get("description_short") or payload.get("description") or raw_text
        date_start, date_end = parse_dates(raw_text)
        venue = payload.get("organization", {}).get("name") if isinstance(payload.get("organization"), dict) else payload.get("venue", "")
        address = payload.get("location") or payload.get("address") or ""
        price_min, price_max = parse_price(raw_text + " " + description)
        age_limit = payload.get("age_restriction") or parse_age(raw_text)
        source_url = payload.get("url") or payload.get("link") or ""
        images = []
        poster = payload.get("poster_image")
        if poster:
            images.append(str(poster))
        confidence = 0.8 if title and date_start else 0.55
        candidate = NormalizedCandidate(
            title=title,
            description=description,
            date_start=date_start,
            date_end=date_end,
            venue=venue or "",
            address=address,
            price_min=price_min,
            price_max=price_max,
            currency="RUB",
            age_limit=age_limit or "",
            tags=[],
            images=images,
            source_url=source_url,
            parse_confidence=confidence,
        )
        return [candidate]
