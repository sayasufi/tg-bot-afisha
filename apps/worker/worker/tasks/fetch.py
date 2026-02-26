import asyncio
from datetime import datetime, timezone

import httpx

from connectors.telegram.telethon_connector import TelethonConnector
from connectors.web.kudago_connector import KudaGoConnector
from core.config.settings import get_settings
from core.db.repositories.ingestion import (
    create_source_run,
    ensure_source,
    finish_source_run,
    get_active_telegram_channels,
    upsert_raw_event,
)
from core.db.session import SessionLocal

from apps.worker.worker.celery_app import celery_app


def _fetch_kudago_page(connector: KudaGoConnector, cursor: str | None) -> tuple[list, str | None]:
    try:
        return asyncio.run(connector.fetch(cursor=cursor))
    except httpx.HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code != 404:
            raise
        # Cursor/page can become invalid as the upstream dataset shifts.
        return asyncio.run(connector.fetch(cursor="1"))


@celery_app.task(bind=True, max_retries=3)
def fetch_kudago(self):
    settings = get_settings()
    db = SessionLocal()
    source = ensure_source(
        db,
        "kudago",
        "web",
        settings.kudago_base_url,
        {"cursor": "1", "location": "msk", "page_size": 100},
    )
    run = create_source_run(db, source.source_id)
    try:
        cursor = source.config_json.get("cursor")
        location = source.config_json.get("location", "msk")
        page_size = int(source.config_json.get("page_size", 100))
        connector = KudaGoConnector(location=location, page_size=page_size)
        records, next_cursor = _fetch_kudago_page(connector, cursor)
        for rec in records:
            upsert_raw_event(db, source.source_id, rec.external_id, rec.payload, rec.raw_text)
        source.config_json = {**source.config_json, "cursor": next_cursor}
        db.add(source)
        db.commit()
        finish_source_run(db, run, "success", {"fetched": len(records)})
        return {"fetched": len(records), "cursor": next_cursor}
    except Exception as exc:
        finish_source_run(db, run, "failed", {"fetched": 0}, repr(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def fetch_kudago_full_scan(self):
    settings = get_settings()
    db = SessionLocal()
    source = ensure_source(
        db,
        "kudago",
        "web",
        settings.kudago_base_url,
        {"cursor": "1", "location": "msk", "page_size": 100},
    )
    run = create_source_run(db, source.source_id)
    try:
        location = source.config_json.get("location", "msk")
        page_size = int(source.config_json.get("page_size", 100))
        max_pages = int(source.config_json.get("full_scan_max_pages", 50))
        connector = KudaGoConnector(location=location, page_size=page_size)

        cursor: str | None = "1"
        pages_scanned = 0
        total_fetched = 0
        stop_reason = "max_pages"
        while cursor and pages_scanned < max_pages:
            records, next_cursor = _fetch_kudago_page(connector, cursor)
            pages_scanned += 1
            for rec in records:
                upsert_raw_event(db, source.source_id, rec.external_id, rec.payload, rec.raw_text)
            total_fetched += len(records)

            # Connector keeps only in-window events; empty page means we can stop the scan.
            if not records:
                stop_reason = "no_in_window_records"
                break

            if next_cursor == cursor:
                stop_reason = "cursor_stable"
                break
            cursor = next_cursor
            stop_reason = "completed_iteration"

        source.config_json = {**source.config_json, "cursor": cursor or "1"}
        db.add(source)
        db.commit()
        stats = {
            "fetched": total_fetched,
            "pages_scanned": pages_scanned,
            "stop_reason": stop_reason,
            "next_cursor": cursor,
        }
        finish_source_run(db, run, "success", stats)
        return stats
    except Exception as exc:
        finish_source_run(db, run, "failed", {"fetched": 0}, repr(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def fetch_telegram_public(self):
    db = SessionLocal()
    channels = get_active_telegram_channels(db)
    if not channels:
        return {"channels": 0, "fetched": 0}

    total_fetched = 0
    runs_summary: list[dict] = []

    try:
        for channel_row in channels:
            channel = channel_row.username.lstrip("@").strip().lower()
            if not channel:
                continue

            source_name = f"telegram_public:{channel}"
            source = ensure_source(
                db,
                source_name,
                "telegram",
                f"https://t.me/{channel}",
                {"cursor": None, "channel": channel, "city_id": channel_row.city_id},
            )
            run = create_source_run(db, source.source_id)
            try:
                cursor = source.config_json.get("cursor")
                connector = TelethonConnector(channel)
                records, next_cursor = asyncio.run(connector.fetch(cursor=cursor))
                for rec in records:
                    upsert_raw_event(db, source.source_id, rec.external_id, rec.payload, rec.raw_text)
                source.config_json = {
                    **source.config_json,
                    "channel": channel,
                    "city_id": channel_row.city_id,
                    "cursor": next_cursor,
                    "last_fetch": datetime.now(timezone.utc).isoformat(),
                }
                db.add(source)
                db.commit()
                finish_source_run(db, run, "success", {"fetched": len(records), "channel": channel})
                total_fetched += len(records)
                runs_summary.append({"channel": channel, "fetched": len(records), "cursor": next_cursor})
            except Exception as exc:
                finish_source_run(db, run, "failed", {"fetched": 0, "channel": channel}, str(exc))
                raise

        return {"channels": len(runs_summary), "fetched": total_fetched, "runs": runs_summary}
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()


