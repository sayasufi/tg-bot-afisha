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


async def _fetch_kudago_page(connector: KudaGoConnector, cursor: str | None) -> tuple[list, str | None]:
    try:
        return await connector.fetch(cursor=cursor)
    except httpx.HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code != 404:
            raise
        # Cursor/page can become invalid as the upstream dataset shifts.
        return await connector.fetch(cursor="1")


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
            # Date order so pagination walks the window soonest-first and ends when
            # it runs past it (instead of trawling years of -publication_date pages).
            connector = KudaGoConnector(location=location, page_size=page_size, order_by="dates")

            cursor: str | None = "1"
            pages_scanned = 0
            total_fetched = 0
            stop_reason = "max_pages"
            while cursor and pages_scanned < max_pages:
                records, next_cursor = await _fetch_kudago_page(connector, cursor)
                pages_scanned += 1
                await bulk_upsert_raw_events(db, source.source_id, records)
                total_fetched += len(records)

                # Don't stop just because THIS page had no in-window events — with
                # -publication_date ordering a far-future event published long ago
                # sits on a deep page behind pages of already-passed events. Page
                # only until the API itself runs out (cursor stops advancing).
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
            try:
                records, next_cursor = await connector.fetch(cursor=cursor)
            except Exception as exc:
                # Yandex's actualEvents resolver times out (its own ~600ms budget) for DEEP offsets — past
                # ~6000 of the ~6360-event Moscow catalogue the tail is simply unreachable via offset
                # pagination. Without this, the incremental cursor sticks at the first failing offset and
                # the WHOLE source dies: every run re-fetches the same dead page, nothing refreshes, and the
                # catalogue drains as events expire. Treat a deep-page timeout as end-of-catalogue — wrap to
                # 0 and keep cycling (the far-future tail resurfaces later as those events move to lower
                # offsets). A failure at offset 0 is a genuine outage, so re-raise that.
                if cursor and str(cursor) != "0":
                    print(f"yandex: deep-offset timeout at {cursor} — wrapping cursor to 0 (tail unreachable): {exc!r}")
                    source.config_json = {**source.config_json, "cursor": "0"}
                    db.add(source)
                    await db.commit()
                    await finish_source_run(db, run, "success", {"fetched": 0, "wrapped_from": cursor})
                    return {"fetched": 0, "wrapped_from": cursor}
                raise
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

            async def _persist(recs):
                # Per-page durable write (bulk_upsert commits) so a crash mid-scan
                # keeps everything fetched so far instead of losing the whole sweep.
                await bulk_upsert_raw_events(db, source.source_id, recs)

            # One session/handshake paginates the whole in-window catalogue.
            records, pages_scanned, stop_reason = await connector.scan(max_pages=max_pages, on_page=_persist)

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


async def _fetch_afisha_impl() -> dict:
    settings = get_settings()
    if not settings.afisha_enabled:
        return {"fetched": 0, "skipped": "afisha disabled"}
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


async def _fetch_afisha_full_scan_impl() -> dict:
    settings = get_settings()
    if not settings.afisha_enabled:
        return {"fetched": 0, "skipped": "afisha disabled"}
    async with WorkerAsyncSessionLocal() as db:
        source = await ensure_source(db, "afisha_ru", "web", settings.afisha_ru_base_url, _afisha_config())
        run = await create_source_run(db, source.source_id)
        try:
            city = source.config_json.get("city", DEFAULT_CITY.afisha_city)
            max_pages = int(source.config_json.get("full_scan_max_pages", 80))
            connector = AfishaRuConnector(city=city, proxy=settings.afisha_proxy or None)

            async def _persist(recs):
                # bulk_upsert commits internally, so each page is durable as it's
                # fetched — a crash mid-scan keeps everything fetched so far.
                await bulk_upsert_raw_events(db, source.source_id, recs)

            records, pages_scanned, stop_reason = await connector.scan(max_pages=max_pages, on_page=_persist)
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
