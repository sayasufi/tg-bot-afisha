"""One-off backfill: re-classify categories (with source hints) and re-parse
prices for events already in the DB, using the improved pipeline code.

Safe by design:
  * category is decided from the structured source's own label first (reliable),
    and only falls back to the LLM for untyped/free-text events; categories are
    left as-is if the LLM is the only option AND it's unreachable.
  * prices are only written when the source price field actually parses.
  * dates/venues/images are never touched.

Usage (inside the worker/api container):
    python -m scripts.backfill_categories_prices            # full run
    python -m scripts.backfill_categories_prices --limit 5  # dry-ish sample
"""
import argparse
import asyncio

from sqlalchemy import select

from core.categorization import map_source_category
from core.db.models import Event, EventOccurrence, EventSource, RawEvent
from core.db.session import SessionLocal
from pipeline.llm.service import LLMService
from pipeline.normalizer.extractors import parse_price_field


def _source_hints(payload: dict) -> list[str]:
    hints: list[str] = []
    for key in ("categories", "tags"):
        values = payload.get(key)
        if isinstance(values, list):
            for item in values:
                if isinstance(item, str):
                    hints.append(item)
                elif isinstance(item, dict) and item.get("slug"):
                    hints.append(str(item["slug"]))
    return list(dict.fromkeys(hints))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    db = SessionLocal()
    llm = LLMService()
    stats = {"seen": 0, "cat_changed": 0, "cat_kept": 0, "priced": 0, "llm_down": 0, "from_source": 0, "from_llm": 0}
    try:
        events = db.execute(select(Event)).scalars().all()
        if args.limit:
            events = events[: args.limit]
        for e in events:
            stats["seen"] += 1
            src = db.execute(
                select(EventSource).where(EventSource.event_id == e.event_id).order_by(EventSource.id.asc())
            ).scalars().first()
            payload: dict = {}
            hints: list[str] = []
            source_name = ""
            if src:
                raw = db.get(RawEvent, src.raw_id)
                if raw:
                    source_name = raw.source.name if raw.source else ""
                    if isinstance(raw.raw_payload_json, dict):
                        payload = raw.raw_payload_json
                        hints = _source_hints(payload)

            # 1) Category: trust the structured source's own label first; fall back
            #    to the LLM only for untyped/free-text events.
            category = map_source_category(hints, source_name)
            if category is not None:
                stats["from_source"] += 1
                old = e.category
                e.category = category
                stats["cat_changed" if category != old else "cat_kept"] += 1
                db.add(e)
            else:
                res = asyncio.run(llm.classify(e.canonical_title, e.canonical_description or "", hints))
                if res.provider == "fallback":
                    stats["llm_down"] += 1
                else:
                    stats["from_llm"] += 1
                    old = e.category
                    e.category = res.category
                    if res.subcategory:
                        e.subcategory = res.subcategory
                    stats["cat_changed" if res.category != old else "cat_kept"] += 1
                    db.add(e)

            # 2) Re-parse price from the source's dedicated field.
            pmin, pmax = parse_price_field(str(payload.get("price") or ""))
            if pmin is None and pmax is None and payload.get("is_free") is True:
                pmin, pmax = 0.0, 0.0
            if pmin is not None or pmax is not None:
                occs = db.execute(
                    select(EventOccurrence).where(EventOccurrence.event_id == e.event_id)
                ).scalars().all()
                for occ in occs:
                    occ.price_min = pmin
                    occ.price_max = pmax
                    db.add(occ)
                if occs:
                    stats["priced"] += 1

            db.commit()
        print("BACKFILL DONE:", stats)
    finally:
        db.close()


if __name__ == "__main__":
    main()
