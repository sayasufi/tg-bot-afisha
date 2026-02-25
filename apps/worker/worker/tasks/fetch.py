import asyncio
from datetime import datetime, timezone

from connectors.telegram.forward_inbox_connector import ForwardInboxConnector
from connectors.telegram.telethon_connector import TelethonConnector
from connectors.web.timepad_connector import TimepadConnector
from core.config.settings import get_settings
from core.db.repositories.ingestion import (
    create_source_run,
    ensure_source,
    finish_source_run,
    get_unprocessed_inbox_rows,
    mark_inbox_processed,
    upsert_raw_event,
)
from core.db.session import SessionLocal

from apps.worker.worker.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3)
def fetch_timepad(self):
    settings = get_settings()
    db = SessionLocal()
    source = ensure_source(db, "timepad", "web", settings.timepad_base_url, {"cursor": None})
    run = create_source_run(db, source.source_id)
    try:
        cursor = source.config_json.get("cursor")
        connector = TimepadConnector()
        records, next_cursor = asyncio.run(connector.fetch(cursor=cursor))
        for rec in records:
            upsert_raw_event(db, source.source_id, rec.external_id, rec.payload, rec.raw_text)
        source.config_json = {**source.config_json, "cursor": next_cursor}
        db.add(source)
        db.commit()
        finish_source_run(db, run, "success", {"fetched": len(records)})
        return {"fetched": len(records), "cursor": next_cursor}
    except Exception as exc:
        finish_source_run(db, run, "failed", {"fetched": 0}, str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def fetch_telegram_public(self):
    settings = get_settings()
    db = SessionLocal()
    source = ensure_source(db, "telegram_public", "telegram", "https://t.me", {"cursor": None, "channel": "events"})
    run = create_source_run(db, source.source_id)
    try:
        cursor = source.config_json.get("cursor")
        channel = source.config_json.get("channel", "events")
        connector = TelethonConnector(channel)
        records, next_cursor = asyncio.run(connector.fetch(cursor=cursor))
        for rec in records:
            upsert_raw_event(db, source.source_id, rec.external_id, rec.payload, rec.raw_text)
        source.config_json = {**source.config_json, "cursor": next_cursor, "last_fetch": datetime.now(timezone.utc).isoformat()}
        db.add(source)
        db.commit()
        finish_source_run(db, run, "success", {"fetched": len(records)})
        return {"fetched": len(records), "cursor": next_cursor}
    except Exception as exc:
        finish_source_run(db, run, "failed", {"fetched": 0}, str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def fetch_forward_inbox(self):
    db = SessionLocal()
    source = ensure_source(db, "telegram_forward_inbox", "telegram", "telegram://forwarded", {})
    run = create_source_run(db, source.source_id)
    try:
        rows = get_unprocessed_inbox_rows(db)
        count = 0
        for row in rows:
            rec = ForwardInboxConnector.to_raw_record(row)
            upsert_raw_event(db, source.source_id, rec.external_id, rec.payload, rec.raw_text)
            mark_inbox_processed(db, row.inbox_id)
            count += 1
        finish_source_run(db, run, "success", {"fetched": count})
        return {"fetched": count}
    except Exception as exc:
        finish_source_run(db, run, "failed", {"fetched": 0}, str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()
