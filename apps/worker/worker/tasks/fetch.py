import asyncio
from datetime import datetime, timezone

import httpx

from connectors.telegram.telethon_connector import TelethonConnector
from connectors.telegram.web_preview_connector import TelegramWebPreviewConnector
from connectors.web.afisha_ru_connector import AfishaRuConnector
from connectors.web.kudago_connector import KudaGoConnector
from connectors.web.yandex_afisha_connector import YandexAfishaConnector
from core.cities import DEFAULT_CITY
from core.config.settings import get_settings
from core.db.repositories.ingestion import (
    bulk_upsert_raw_events,
    create_source_run,
    ensure_source,
    finish_source_run,
    get_active_telegram_channels,
)
from core.db.session import WorkerAsyncSessionLocal
from core.tasklock import single_instance

from apps.worker.worker.celery_app import celery_app


async def _fetch_kudago_page(connector: KudaGoConnector, cursor: str | None) -> tuple[list, str | None]:
    try:
        return await connector.fetch(cursor=cursor)
    except httpx.HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code != 404:
            raise
        # Cursor/page can become invalid as the upstream dataset shifts.
        return await connector.fetch(cursor="1")


@celery_app.task(bind=True, max_retries=3)
@single_instance("fetch_kudago")
def fetch_kudago(self):
    try:
        return asyncio.run(_fetch_kudago_impl())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _fetch_kudago_impl() -> dict:
    settings = get_settings()
    async with WorkerAsyncSessionLocal() as db:
        source = await ensure_source(
            db, "kudago", "web", settings.kudago_base_url,
            {"cursor": "1", "location": DEFAULT_CITY.kudago_location, "page_size": 100},
        )
        run = await create_source_run(db, source.source_id)
        try:
            cursor = source.config_json.get("cursor")
            location = source.config_json.get("location", DEFAULT_CITY.kudago_location)
            page_size = int(source.config_json.get("page_size", 100))
            connector = KudaGoConnector(location=location, page_size=page_size)
            records, next_cursor = await _fetch_kudago_page(connector, cursor)
            await bulk_upsert_raw_events(db, source.source_id, records)
            source.config_json = {**source.config_json, "cursor": next_cursor}
            db.add(source)
            await db.commit()
            await finish_source_run(db, run, "success", {"fetched": len(records)})
            return {"fetched": len(records), "cursor": next_cursor}
        except Exception as exc:
            await db.rollback()
            await finish_source_run(db, run, "failed", {"fetched": 0}, repr(exc))
            raise


@celery_app.task(bind=True, max_retries=3)
@single_instance("fetch_kudago")
def fetch_kudago_full_scan(self):
    try:
        return asyncio.run(_fetch_kudago_full_scan_impl())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _fetch_kudago_full_scan_impl() -> dict:
    settings = get_settings()
    async with WorkerAsyncSessionLocal() as db:
        source = await ensure_source(
            db, "kudago", "web", settings.kudago_base_url,
            {"cursor": "1", "location": DEFAULT_CITY.kudago_location, "page_size": 100},
        )
        run = await create_source_run(db, source.source_id)
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
                records, next_cursor = await _fetch_kudago_page(connector, cursor)
                pages_scanned += 1
                await bulk_upsert_raw_events(db, source.source_id, records)
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
            await db.commit()
            stats = {
                "fetched": total_fetched,
                "pages_scanned": pages_scanned,
                "stop_reason": stop_reason,
                "next_cursor": cursor,
            }
            await finish_source_run(db, run, "success", stats)
            return stats
        except Exception as exc:
            await db.rollback()
            await finish_source_run(db, run, "failed", {"fetched": 0}, repr(exc))
            raise


def _yandex_config() -> dict:
    return {"cursor": "0", "city": DEFAULT_CITY.yandex_city, "page_size": 100}


@celery_app.task(bind=True, max_retries=3)
@single_instance("fetch_yandex_afisha")
def fetch_yandex_afisha(self):
    """Incremental Yandex Afisha fetch: one page of the city feed per tick. The
    paging offset advances and wraps back to 0 once the in-window catalogue is
    exhausted, so repeated ticks keep the data fresh."""
    try:
        return asyncio.run(_fetch_yandex_impl())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _fetch_yandex_impl() -> dict:
    settings = get_settings()
    async with WorkerAsyncSessionLocal() as db:
        source = await ensure_source(db, "yandex_afisha", "web", settings.yandex_afisha_base_url, _yandex_config())
        run = await create_source_run(db, source.source_id)
        try:
            cursor = source.config_json.get("cursor", "0")
            city = source.config_json.get("city", DEFAULT_CITY.yandex_city)
            page_size = int(source.config_json.get("page_size", 100))
            connector = YandexAfishaConnector(city=city, page_size=page_size)
            records, next_cursor = await connector.fetch(cursor=cursor)
            await bulk_upsert_raw_events(db, source.source_id, records)
            # Stable cursor (== current) means we reached the end — wrap to restart.
            stored_cursor = "0" if next_cursor == cursor else next_cursor
            source.config_json = {**source.config_json, "cursor": stored_cursor}
            db.add(source)
            await db.commit()
            await finish_source_run(db, run, "success", {"fetched": len(records)})
            return {"fetched": len(records), "cursor": stored_cursor}
        except Exception as exc:
            await db.rollback()
            await finish_source_run(db, run, "failed", {"fetched": 0}, repr(exc))
            raise


@celery_app.task(bind=True, max_retries=3)
@single_instance("fetch_yandex_afisha")
def fetch_yandex_afisha_full_scan(self):
    """Full sweep of the in-window Yandex Afisha catalogue: page through every
    offset until the feed is exhausted (or max_pages), upserting each event."""
    try:
        return asyncio.run(_fetch_yandex_full_scan_impl())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _fetch_yandex_full_scan_impl() -> dict:
    settings = get_settings()
    async with WorkerAsyncSessionLocal() as db:
        source = await ensure_source(db, "yandex_afisha", "web", settings.yandex_afisha_base_url, _yandex_config())
        run = await create_source_run(db, source.source_id)
        try:
            city = source.config_json.get("city", DEFAULT_CITY.yandex_city)
            page_size = int(source.config_json.get("page_size", 100))
            max_pages = int(source.config_json.get("full_scan_max_pages", 40))
            connector = YandexAfishaConnector(city=city, page_size=page_size)

            # One session/handshake paginates the whole in-window catalogue.
            records, pages_scanned, stop_reason = await connector.scan(max_pages=max_pages)
            await bulk_upsert_raw_events(db, source.source_id, records)

            source.config_json = {**source.config_json, "cursor": "0"}
            db.add(source)
            await db.commit()
            stats = {"fetched": len(records), "pages_scanned": pages_scanned, "stop_reason": stop_reason}
            await finish_source_run(db, run, "success", stats)
            return stats
        except Exception as exc:
            await db.rollback()
            await finish_source_run(db, run, "failed", {"fetched": 0}, repr(exc))
            raise


def _afisha_config() -> dict:
    return {"cursor": "0", "city": DEFAULT_CITY.afisha_city}


@celery_app.task(bind=True, max_retries=3)
@single_instance("fetch_afisha_ru")
def fetch_afisha_ru(self):
    """Incremental afisha.ru fetch: refresh the soonest page of one rubric per
    tick (cursor cycles through rubrics), reading the server-rendered listing."""
    try:
        return asyncio.run(_fetch_afisha_impl())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _fetch_afisha_impl() -> dict:
    settings = get_settings()
    if not settings.afisha_proxy:
        # afisha blocks cloud IPs (e.g. GCP); ingestion stays off until a
        # residential proxy is set via AFISHA_PROXY. No-op rather than 429-spam.
        return {"fetched": 0, "skipped": "no AFISHA_PROXY"}
    async with WorkerAsyncSessionLocal() as db:
        source = await ensure_source(db, "afisha_ru", "web", settings.afisha_ru_base_url, _afisha_config())
        run = await create_source_run(db, source.source_id)
        try:
            cursor = source.config_json.get("cursor", "0")
            city = source.config_json.get("city", DEFAULT_CITY.afisha_city)
            connector = AfishaRuConnector(city=city, proxy=settings.afisha_proxy)
            records, next_cursor = await connector.fetch(cursor=cursor)
            await bulk_upsert_raw_events(db, source.source_id, records)
            source.config_json = {**source.config_json, "cursor": next_cursor}
            db.add(source)
            await db.commit()
            await finish_source_run(db, run, "success", {"fetched": len(records)})
            return {"fetched": len(records), "cursor": next_cursor}
        except Exception as exc:
            await db.rollback()
            await finish_source_run(db, run, "failed", {"fetched": 0}, repr(exc))
            raise


@celery_app.task(bind=True, max_retries=3)
@single_instance("fetch_afisha_ru")
def fetch_afisha_ru_full_scan(self):
    """Full in-window sweep of every afisha.ru rubric, paging until the date-sorted
    feed leaves the lookahead window (or max_pages)."""
    try:
        return asyncio.run(_fetch_afisha_full_scan_impl())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _fetch_afisha_full_scan_impl() -> dict:
    settings = get_settings()
    if not settings.afisha_proxy:
        return {"fetched": 0, "skipped": "no AFISHA_PROXY"}
    async with WorkerAsyncSessionLocal() as db:
        source = await ensure_source(db, "afisha_ru", "web", settings.afisha_ru_base_url, _afisha_config())
        run = await create_source_run(db, source.source_id)
        try:
            city = source.config_json.get("city", DEFAULT_CITY.afisha_city)
            max_pages = int(source.config_json.get("full_scan_max_pages", 80))
            connector = AfishaRuConnector(city=city, proxy=settings.afisha_proxy)
            records, pages_scanned, stop_reason = await connector.scan(max_pages=max_pages)
            await bulk_upsert_raw_events(db, source.source_id, records)
            source.config_json = {**source.config_json, "cursor": "0"}
            db.add(source)
            await db.commit()
            stats = {"fetched": len(records), "pages_scanned": pages_scanned, "stop_reason": stop_reason}
            await finish_source_run(db, run, "success", stats)
            return stats
        except Exception as exc:
            await db.rollback()
            await finish_source_run(db, run, "failed", {"fetched": 0}, repr(exc))
            raise


@celery_app.task(bind=True, max_retries=3)
@single_instance("fetch_telegram")
def fetch_telegram_public(self):
    try:
        return asyncio.run(_fetch_telegram_impl())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _fetch_telegram_impl() -> dict:
    settings = get_settings()
    use_telethon = bool(settings.telethon_api_id and settings.telethon_api_hash)
    total_fetched = 0
    runs_summary: list[dict] = []
    async with WorkerAsyncSessionLocal() as db:
        channels = await get_active_telegram_channels(db)
        if not channels:
            return {"channels": 0, "fetched": 0}
        for channel_row in channels:
            channel = channel_row.username.lstrip("@").strip().lower()
            if not channel:
                continue

            source = await ensure_source(
                db,
                f"telegram_public:{channel}",
                "telegram",
                f"https://t.me/{channel}",
                {"cursor": None, "channel": channel, "city_id": channel_row.city_id},
            )
            run = await create_source_run(db, source.source_id)
            try:
                cursor = source.config_json.get("cursor")
                connector = TelethonConnector(channel) if use_telethon else TelegramWebPreviewConnector(channel)
                records, next_cursor = await connector.fetch(cursor=cursor)
                await bulk_upsert_raw_events(db, source.source_id, records)
                source.config_json = {
                    **source.config_json,
                    "channel": channel,
                    "city_id": channel_row.city_id,
                    "cursor": next_cursor,
                    "last_fetch": datetime.now(timezone.utc).isoformat(),
                }
                db.add(source)
                await db.commit()
                await finish_source_run(db, run, "success", {"fetched": len(records), "channel": channel})
                total_fetched += len(records)
                runs_summary.append({"channel": channel, "fetched": len(records), "cursor": next_cursor})
            except Exception as exc:
                await db.rollback()
                await finish_source_run(db, run, "failed", {"fetched": 0, "channel": channel}, str(exc))
                raise

    return {"channels": len(runs_summary), "fetched": total_fetched, "runs": runs_summary}
