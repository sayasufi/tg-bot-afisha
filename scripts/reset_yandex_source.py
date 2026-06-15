"""One-off reset of the Yandex Afisha source so it rebuilds with the fixed pipeline.

Existing yandex events were ingested before per-session times (eventScheduleOther)
and one-occurrence-per-showtime landed, so they show "время уточняйте" with a single
date. `normalize` never reprocesses a raw event that already has a candidate, so the
fix can't reach them in place — this script drops the yandex pipeline artifacts and
lets a fresh fetch -> normalize -> enrich -> dedup rebuild them correctly.

Deletes (for the yandex_afisha source): EventSource links, the EventOccurrences and
Events that become orphaned (no other source), EventCandidates, and RawEvents. Events
also linked from another source (e.g. KudaGo) are kept and simply re-deduped on the
next run.

    python -m scripts.reset_yandex_source            # dry run (counts only)
    python -m scripts.reset_yandex_source --apply     # actually delete
"""
import argparse

from sqlalchemy import func, select

from core.db.models import Event, EventCandidate, EventOccurrence, EventSource, RawEvent, Source
from core.db.session import SessionLocal

SOURCE_NAME = "yandex_afisha"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="perform the deletion (otherwise dry run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        src = db.execute(select(Source).where(Source.name == SOURCE_NAME)).scalar_one_or_none()
        if not src:
            print(f"no '{SOURCE_NAME}' source — nothing to do")
            return

        raw_ids = list(db.execute(select(RawEvent.raw_id).where(RawEvent.source_id == src.source_id)).scalars())
        cand_ids = (
            list(db.execute(select(EventCandidate.candidate_id).where(EventCandidate.raw_id.in_(raw_ids))).scalars())
            if raw_ids
            else []
        )
        links = (
            db.execute(select(EventSource).where(EventSource.raw_id.in_(raw_ids))).scalars().all() if raw_ids else []
        )
        event_ids = {link.event_id for link in links}

        # Which of those events are yandex-only (no other source) -> safe to delete.
        orphan_event_ids = []
        for event_id in event_ids:
            others = db.execute(
                select(func.count())
                .select_from(EventSource)
                .where(EventSource.event_id == event_id, EventSource.raw_id.notin_(raw_ids))
            ).scalar()
            if not others:
                orphan_event_ids.append(event_id)

        print(
            f"yandex reset plan: raw={len(raw_ids)} candidates={len(cand_ids)} links={len(links)} "
            f"events_touched={len(event_ids)} orphan_events_to_delete={len(orphan_event_ids)} "
            f"shared_events_kept={len(event_ids) - len(orphan_event_ids)}"
        )
        if not args.apply:
            print("dry run — re-run with --apply to delete")
            return

        for link in links:
            db.delete(link)
        db.flush()

        deleted_occ = 0
        for event_id in orphan_event_ids:
            for occ in db.execute(select(EventOccurrence).where(EventOccurrence.event_id == event_id)).scalars().all():
                db.delete(occ)
                deleted_occ += 1
            event = db.get(Event, event_id)
            if event:
                db.delete(event)
        db.flush()

        for candidate_id in cand_ids:
            candidate = db.get(EventCandidate, candidate_id)
            if candidate:
                db.delete(candidate)
        db.flush()

        for raw_id in raw_ids:
            raw = db.get(RawEvent, raw_id)
            if raw:
                db.delete(raw)

        # Reset the fetch cursor so the next full scan starts from the top.
        src.config_json = {**(src.config_json or {}), "cursor": "0"}
        db.add(src)
        db.commit()
        print(
            f"done: deleted {len(links)} links, {len(orphan_event_ids)} events, {deleted_occ} occurrences, "
            f"{len(cand_ids)} candidates, {len(raw_ids)} raw events. Re-run fetch to rebuild."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
