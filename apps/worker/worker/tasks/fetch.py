import asyncio
from datetime import datetime, timezone

import httpx

from connectors.telegram.telethon_connector import TelethonConnector
from connectors.telegram.web_preview_connector import TelegramWebPreviewConnector
from connectors.web.kudago_connector import KudaGoConnector
from connectors.web.yandex_afisha_connector import YandexAfishaConnector
from core.config.settings import get_settings
from core.db.repositories.ingestion import (
    bulk_upsert_raw_events,
    create_source_run,
    ensure_source,
    finish_source_run,
    get_active_telegram_channels,
)
from core.cities import DEFAULT_CITY
from core.db.session import SessionLocal
from core.tasklock import single_instance

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
@single_instance("fetch_kudago")
def fetch_kudago(self):
    settings = get_settings()
    db = SessionLocal()
    source = ensure_source(
        db,
        "kudago",
        "web",
        settings.kudago_base_url,
        {"cursor": "1", "location": DEFAULT_CITY.kudago_location, "page_size": 100},
    )
    run = create_source_run(db, source.source_id)
    try:
        cursor = source.config_json.get("cursor")
        location = source.config_json.get("location", DEFAULT_CITY.kudago_location)
        page_size = int(source.config_json.get("page_size", 100))
        connector = KudaGoConnector(location=location, page_size=page_size)
        records, next_cursor = _fetch_kudago_page(connector, cursor)
        bulk_upsert_raw_events(db, source.source_id, records)
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
@single_instance("fetch_kudago")
def fetch_kudago_full_scan(self):
    settings = get_settings()
    db = SessionLocal()
    source = ensure_source(
        db,
        "kudago",
        "web",
        settings.kudago_base_url,
        {"cursor": "1", "location": DEFAULT_CITY.kudago_location, "page_size": 100},
    )
    run = create_source_run(db, source.source_id)
    try:
        location = source.config_json.get("location", DEFAULT_CITY.kudago_location)
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
            bulk_upsert_raw_events(db, source.source_id, records)
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


def _yandex_config(settings) -> dict:
    return {"cursor": "0", "city": DEFAULT_CITY.yandex_city, "page_size": 100}


@celery_app.task(bind=True, max_retries=3)
@single_instance("fetch_yandex_afisha")
def fetch_yandex_afisha(self):
    """Incremental Yandex Afisha fetch: one page of the city feed per tick. The
    paging offset advances and wraps back to 0 once the in-window catalogue is
    exhausted, so repeated ticks keep the data fresh."""
    settings = get_settings()
    db = SessionLocal()
    source = ensure_source(db, "yandex_afisha", "web", settings.yandex_afisha_base_url, _yandex_config(settings))
    run = create_source_run(db, source.source_id)
    try:
        cursor = source.config_json.get("cursor", "0")
        city = source.config_json.get("city", DEFAULT_CITY.yandex_city)
        page_size = int(source.config_json.get("page_size", 100))
        connector = YandexAfishaConnector(city=city, page_size=page_size)
        records, next_cursor = asyncio.run(connector.fetch(cursor=cursor))
        bulk_upsert_raw_events(db, source.source_id, records)
        # Stable cursor (== current) means we reached the end — wrap to restart.
        stored_cursor = "0" if next_cursor == cursor else next_cursor
        source.config_json = {**source.config_json, "cursor": stored_cursor}
        db.add(source)
        db.commit()
        finish_source_run(db, run, "success", {"fetched": len(records)})
        return {"fetched": len(records), "cursor": stored_cursor}
    except Exception as exc:
        finish_source_run(db, run, "failed", {"fetched": 0}, repr(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
@single_instance("fetch_yandex_afisha")
def fetch_yandex_afisha_full_scan(self):
    """Full sweep of the in-window Yandex Afisha catalogue: page through every
    offset until the feed is exhausted (or max_pages), upserting each event."""
    settings = get_settings()
    db = SessionLocal()
    source = ensure_source(db, "yandex_afisha", "web", settings.yandex_afisha_base_url, _yandex_config(settings))
    run = create_source_run(db, source.source_id)
    try:
        city = source.config_json.get("city", DEFAULT_CITY.yandex_city)
        page_size = int(source.config_json.get("page_size", 100))
        max_pages = int(source.config_json.get("full_scan_max_pages", 40))
        connector = YandexAfishaConnector(city=city, page_size=page_size)

        # One session/handshake paginates the whole in-window catalogue.
        records, pages_scanned, stop_reason = asyncio.run(connector.scan(max_pages=max_pages))
        bulk_upsert_raw_events(db, source.source_id, records)

        source.config_json = {**source.config_json, "cursor": "0"}
        db.add(source)
        db.commit()
        stats = {"fetched": len(records), "pages_scanned": pages_scanned, "stop_reason": stop_reason}
        finish_source_run(db, run, "success", stats)
        return stats
    except Exception as exc:
        finish_source_run(db, run, "failed", {"fetched": 0}, repr(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
@single_instance("fetch_telegram")
def fetch_telegram_public(self):
    settings = get_settings()
    db = SessionLocal()
    channels = get_active_telegram_channels(db)
    if not channels:
        return {"channels": 0, "fetched": 0}

    use_telethon = bool(settings.telethon_api_id and settings.telethon_api_hash)

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
                if use_telethon:
                    connector = TelethonConnector(channel)
                else:
                    # No MTProto credentials: scrape the public t.me/s/ preview instead.
                    connector = TelegramWebPreviewConnector(channel)
                records, next_cursor = asyncio.run(connector.fetch(cursor=cursor))
                bulk_upsert_raw_events(db, source.source_id, records)
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


