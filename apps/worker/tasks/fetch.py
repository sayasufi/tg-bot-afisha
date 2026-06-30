import asyncio
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from connectors.telegram.telethon_connector import TelethonConnector
from connectors.telegram.web_preview_connector import PreviewUnavailable, TelegramWebPreviewConnector
from connectors.web.afisha_ru_connector import AfishaRuConnector
from connectors.web.kudago_connector import KudaGoConnector
from connectors.web.timepad_connector import TimepadConnector
from connectors.web.yandex_afisha_connector import YandexAfishaConnector
from core.domain.cities import DEFAULT_CITY, active_cities
from core.config.effective import get_effective
from core.config.settings import get_settings
from core.db.repositories.ingestion import (
    bulk_upsert_raw_events,
    create_source_run,
    ensure_source,
    finish_source_run,
    get_active_telegram_channels,
)
from core.db.session import WorkerAsyncSessionLocal


def _src(base: str, city) -> str:
    """Per-city source identity. The default city keeps the bare connector name so its existing
    source row + pagination cursor are preserved; every other active city gets a slug suffix
    (e.g. ``kudago-spb``) with its own cursor. A city that is active=False is never looped."""
    return base if city.slug == DEFAULT_CITY.slug else f"{base}-{city.slug}"


async def _source_active(db, name: str) -> bool:
    """True если источник активен ИЛИ ещё не создан (первый фетч). Гейт тогла из админки
    (ref.sources.is_active=false → пропускаем источник до запроса/записи). Источник без строки = активен."""
    row = (await db.execute(text("SELECT is_active FROM ref.sources WHERE name = :n"), {"n": name})).first()
    return row is None or bool(row[0])


_PER_CITY_TIMEOUT = 300  # hard wall-clock budget per city in _per_city (one hung connector can't starve the rest)


async def _per_city(one, source_base: str | None = None) -> dict:
    """Run a single-city fetch ``one(db, city)`` for every ACTIVE city, sharing one DB session.
    A city's failure is recorded under its slug and skipped — it never aborts the others (so a
    SPb outage can't stall Moscow, and vice versa). While SPb is active=False this loops Moscow
    only, i.e. behaves exactly as the old single-city flow until the second city is switched on.
    source_base задан → выключенные из админки источники (ref.sources.is_active=false) пропускаются."""
    out: dict = {}
    async with WorkerAsyncSessionLocal() as db:
        for city in active_cities():
            if source_base and not await _source_active(db, _src(source_base, city)):
                out[city.slug] = {"skipped": "disabled"}
                continue
            try:
                # Hard per-city budget: a connector whose HTTP client hangs (slow upstream / half-open
                # socket) must not consume the whole flow's timeout and starve the other ~15 cities. 300s
                # is generous for a full city scan; on timeout the city is cancelled + recorded, others go on.
                out[city.slug] = await asyncio.wait_for(one(db, city), timeout=_PER_CITY_TIMEOUT)
            except asyncio.TimeoutError:
                await db.rollback()
                out[city.slug] = {"error": "per-city timeout"}
            except Exception as exc:  # the inner flow already recorded the failed source_run
                await db.rollback()
                out[city.slug] = {"error": repr(exc)}
    return out


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
    return await _per_city(_kudago_one, "kudago")


async def _kudago_one(db, city) -> dict:
    if not city.kudago_location:
        return {"skipped": "no kudago"}
    settings = get_settings()
    source = await ensure_source(
        db, _src("kudago", city), "web", settings.kudago_base_url,
        {"cursor": "1", "location": city.kudago_location, "page_size": 100},
    )
    run = await create_source_run(db, source.source_id)
    try:
        cursor = source.config_json.get("cursor")
        location = source.config_json.get("location", city.kudago_location)
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


async def _fetch_timepad_impl() -> dict:
    """One curated Timepad sweep per active city: the connector fetches the whitelisted cultural
    categories, collapses recurrences and drops junk, returning ~distinct events. A full scan each
    run (the curated set is small) — no cursor. A no-op when TIMEPAD_TOKEN is unset (connector
    returns []), so it's safe off. Timepad filters by the Russian city NAME (city.name)."""
    return await _per_city(_timepad_one, "timepad")


async def _timepad_one(db, city) -> dict:
    settings = get_settings()
    source = await ensure_source(
        db, _src("timepad", city), "web", settings.timepad_base_url,
        {"city": city.slug, "tp_city": city.name},
    )
    run = await create_source_run(db, source.source_id)
    try:
        connector = TimepadConnector(city=source.config_json.get("tp_city", city.name))
        records, _ = await connector.fetch()
        await bulk_upsert_raw_events(db, source.source_id, records)
        await db.commit()
        await finish_source_run(db, run, "success", {"fetched": len(records)})
        return {"fetched": len(records)}
    except Exception as exc:
        await db.rollback()
        await finish_source_run(db, run, "failed", {"fetched": 0}, repr(exc))
        raise


async def _fetch_kudago_full_scan_impl() -> dict:
    return await _per_city(_kudago_full_scan_one, "kudago")


async def _kudago_full_scan_one(db, city) -> dict:
    if not city.kudago_location:
        return {"skipped": "no kudago"}
    settings = get_settings()
    source = await ensure_source(
        db, _src("kudago", city), "web", settings.kudago_base_url,
        {"cursor": "1", "location": city.kudago_location, "page_size": 100},
    )
    run = await create_source_run(db, source.source_id)
    try:
        location = source.config_json.get("location", city.kudago_location)
        page_size = int(source.config_json.get("page_size", 100))
        max_pages = int(source.config_json.get("full_scan_max_pages", 50))
        # Date order so pagination walks the window soonest-first and ends when
        # it runs past it (instead of trawling years of -publication_date pages).
        connector = KudaGoConnector(location=location, page_size=page_size, order_by="dates")

        cursor: str | None = "1"
        pages_scanned = 0
        total_fetched = 0
        stop_reason = "max_pages"
        # Pages are independent (page-number paging) and the full scan is dates-ordered
        # (soonest-first), so fetch them in CONCURRENT batches and stop once a page comes back
        # empty — i.e. we've paged past the in-window horizon. kudago.com is more fragile than the
        # t.me web (503s/timeouts under load — repeated scans can throttle the IP), so keep the batch
        # small + tolerate a per-page failure (re-fetched next scan); stop if a whole batch fails.
        _PAGE_BATCH = 3
        page = 1
        done = False
        while page <= max_pages and not done:
            batch = [str(p) for p in range(page, min(page + _PAGE_BATCH, max_pages + 1))]
            ok_in_batch = 0
            for res in await asyncio.gather(*(_fetch_kudago_page(connector, c) for c in batch), return_exceptions=True):
                pages_scanned += 1
                if isinstance(res, BaseException):
                    continue  # transient (e.g. 503) — skip this page
                ok_in_batch += 1
                records, _next = res
                await bulk_upsert_raw_events(db, source.source_id, records)
                total_fetched += len(records)
                if not records:
                    done = True  # past the window (dates-ordered)
            if ok_in_batch == 0:
                stop_reason = "errors"
                break
            page += _PAGE_BATCH
            stop_reason = "empty_page" if done else "completed_iteration"
        cursor = None

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


def _yandex_config(city=DEFAULT_CITY) -> dict:
    return {"cursor": "0", "city": city.yandex_city, "page_size": 100}


async def _fetch_yandex_impl() -> dict:
    return await _per_city(_yandex_one, "yandex_afisha")


async def _yandex_one(db, city) -> dict:
    settings = get_settings()
    source = await ensure_source(db, _src("yandex_afisha", city), "web", settings.yandex_afisha_base_url, _yandex_config(city))
    run = await create_source_run(db, source.source_id)
    try:
        cursor = source.config_json.get("cursor", "0")
        ycity = source.config_json.get("city", city.yandex_city)
        page_size = int(source.config_json.get("page_size", 100))
        connector = YandexAfishaConnector(city=ycity, page_size=page_size)
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
                print(f"yandex[{city.slug}]: deep-offset timeout at {cursor} — wrapping cursor to 0 (tail unreachable): {exc!r}")
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
    return await _per_city(_yandex_full_scan_one, "yandex_afisha")


async def _yandex_full_scan_one(db, city) -> dict:
    settings = get_settings()
    source = await ensure_source(db, _src("yandex_afisha", city), "web", settings.yandex_afisha_base_url, _yandex_config(city))
    run = await create_source_run(db, source.source_id)
    try:
        ycity = source.config_json.get("city", city.yandex_city)
        page_size = int(source.config_json.get("page_size", 100))
        max_pages = int(source.config_json.get("full_scan_max_pages", 40))
        connector = YandexAfishaConnector(city=ycity, page_size=page_size)

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


def _afisha_config(city=DEFAULT_CITY) -> dict:
    return {"cursor": "0", "city": city.afisha_city}


async def _fetch_afisha_impl() -> dict:
    if not await get_effective("afisha_enabled", get_settings().afisha_enabled):
        return {"fetched": 0, "skipped": "afisha disabled"}
    return await _per_city(_afisha_one, "afisha_ru")


async def _afisha_one(db, city) -> dict:
    if not city.afisha_city:
        return {"skipped": "no afisha"}
    settings = get_settings()
    source = await ensure_source(db, _src("afisha_ru", city), "web", settings.afisha_ru_base_url, _afisha_config(city))
    run = await create_source_run(db, source.source_id)
    try:
        cursor = source.config_json.get("cursor", "0")
        acity = source.config_json.get("city", city.afisha_city)
        connector = AfishaRuConnector(city=acity, proxy=settings.afisha_proxy)
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
    if not await get_effective("afisha_enabled", get_settings().afisha_enabled):
        return {"fetched": 0, "skipped": "afisha disabled"}
    return await _per_city(_afisha_full_scan_one, "afisha_ru")


async def _afisha_full_scan_one(db, city) -> dict:
    if not city.afisha_city:
        return {"skipped": "no afisha"}
    settings = get_settings()
    source = await ensure_source(db, _src("afisha_ru", city), "web", settings.afisha_ru_base_url, _afisha_config(city))
    run = await create_source_run(db, source.source_id)
    try:
        acity = source.config_json.get("city", city.afisha_city)
        max_pages = int(source.config_json.get("full_scan_max_pages", 80))
        connector = AfishaRuConnector(city=acity, proxy=settings.afisha_proxy or None)

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


_TELEGRAM_CONCURRENCY = 8  # channels at once — a load test showed Telethon is clean to ~16 concurrent
# (floods only at 32, a self-healing 22s wait); 8 keeps headroom for the heavier backfill path.


async def _fetch_telegram_impl() -> dict:
    settings = get_settings()
    # Plain HTTP (public web-preview scraper) is the DEFAULT — no account, no MTProto flood limits, and
    # it parallelises freely. Telethon is kept only as a per-channel FALLBACK for channels whose web
    # preview is disabled (s/ redirects) — detected via PreviewUnavailable below. It needs a session.
    telethon_available = bool(settings.telethon_api_id and settings.telethon_api_hash and settings.telethon_session)
    total_fetched = 0
    runs_summary: list[dict] = []
    async with WorkerAsyncSessionLocal() as db:
        channels = await get_active_telegram_channels(db)
        if not channels:
            return {"channels": 0, "fetched": 0}

        # Pass 1 (serial): ensure each channel's source + run and read its cursor.
        items: list[tuple] = []
        for channel_row in channels:
            channel = channel_row.username.lstrip("@").strip().lower()
            if not channel:
                continue
            source = await ensure_source(
                db, f"telegram_public:{channel}", "telegram", f"https://t.me/{channel}",
                {"cursor": None, "channel": channel, "city_id": channel_row.city_id},
            )
            if not source.is_active:  # тогл источника из админки (ref.sources.is_active) — пропустить канал
                continue
            run = await create_source_run(db, source.source_id)
            items.append((channel_row, channel, source, run, source.config_json.get("cursor")))

        # Pass 2 (CONCURRENT fetch): every channel goes over plain-HTTP web-preview first. Only the few
        # that signal PreviewUnavailable (preview disabled) fall back to Telethon, sharing ONE client
        # (multiplexed over a single MTProto connection — far safer than many clients on one session).
        shared_client = None
        if telethon_available:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            shared_client = TelegramClient(
                StringSession(settings.telethon_session), settings.telethon_api_id, settings.telethon_api_hash
            )
            await shared_client.connect()
        sem = asyncio.Semaphore(_TELEGRAM_CONCURRENCY)

        async def _fetch_channel(channel: str, cursor):
            async with sem:
                try:
                    return await TelegramWebPreviewConnector(channel).fetch(cursor=cursor)
                except PreviewUnavailable:
                    if shared_client is None:
                        raise  # no session → can't reach this channel; surfaced as a failed run
                    return await TelethonConnector(channel).fetch(cursor=cursor, client=shared_client)

        try:
            results = await asyncio.gather(
                *(_fetch_channel(it[1], it[4]) for it in items), return_exceptions=True
            )
        finally:
            if shared_client is not None:
                await shared_client.disconnect()

        # Pass 3 (serial writes): a single async DB session can't be written concurrently.
        for (channel_row, channel, source, run, _cursor), result in zip(items, results):
            if isinstance(result, BaseException):
                msg = str(result)
                # A DEAD username (the channel was deleted/renamed) is permanent — retire it now so it
                # stops erroring every cycle (Telethon raises UsernameNotOccupied/UsernameInvalid; the
                # message carries "No user has <x> as username"). Transient errors — flood-wait, network,
                # redirect — are NOT a death signal, so they keep the channel active for the next cycle.
                dead = type(result).__name__ in ("UsernameNotOccupiedError", "UsernameInvalidError") or "No user has" in msg
                if dead:
                    channel_row.is_active = False
                    db.add(channel_row)
                    print(f"telegram: retired dead channel {channel} ({type(result).__name__})")
                await finish_source_run(db, run, "failed", {"fetched": 0, "channel": channel, "retired": dead}, msg[:300])
                continue
            records, next_cursor = result
            await bulk_upsert_raw_events(db, source.source_id, records)
            source.config_json = {
                **source.config_json,
                "channel": channel,
                "city_id": channel_row.city_id,
                # Optional venue binding (NULL for general channels) → extraction hint + venue/address fill.
                "venue_name": channel_row.venue_name,
                "venue_address": channel_row.venue_address,
                "cursor": next_cursor,
                "last_fetch": datetime.now(timezone.utc).isoformat(),
            }
            db.add(source)
            await db.commit()
            await finish_source_run(db, run, "success", {"fetched": len(records), "channel": channel})
            total_fetched += len(records)
            runs_summary.append({"channel": channel, "fetched": len(records), "cursor": next_cursor})

    return {"channels": len(runs_summary), "fetched": total_fetched, "runs": runs_summary}
