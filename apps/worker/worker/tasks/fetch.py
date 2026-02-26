import asyncio
from datetime import datetime, timezone

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
        records, next_cursor = asyncio.run(connector.fetch(cursor=cursor))
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


