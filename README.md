# tg-bot-afisha MVP

MVP Telegram bot + Telegram Mini App for discovering nearby events from multiple sources.

## Stack

- Backend: FastAPI + SQLAlchemy + Alembic
- Worker: Celery + Redis
- DB: PostgreSQL + PostGIS
- Bot: aiogram 3
- Mini App: React + Vite + Leaflet

## Architecture

- `apps/api`: public REST API for bot and miniapp
- `apps/worker`: ingestion and enrichment pipelines (`fetch -> normalize -> enrich -> dedup`)
- `apps/bot`: Telegram bot, city selection, search, Mini App launch, forwarded ingest inbox
- `connectors`: source plugins (KudaGo API + Telegram)
- `pipeline`: normalizer, deduper, geocoding, LLM classification
- `core`: shared settings/db/models/repositories/logging

## Quick start

```bash
docker compose up --build
```

Services:

- API: http://localhost:8000
- Mini App: http://localhost:5173
- Postgres: localhost:5432
- Redis: localhost:6379

## DB migration

Run inside API container:

```bash
alembic upgrade head
```

## API examples

- `GET /v1/health`
- `GET /v1/ready`
- `GET /v1/events/map?limit=50&categories=concert`
- `GET /v1/events/nearby?lat=55.75&lon=37.61&radius_m=3000`
- `GET /v1/events/{event_id}`
- `POST /v1/search` with JSON: `{"q":"standup friday","city":"Moscow","limit":20}`
- `GET /v1/categories`
- `POST /v1/telegram/validate`

## Worker tasks

- `fetch_kudago`
- `fetch_telegram_public`
- `fetch_forward_inbox`
- `normalize_raw_events`
- `enrich_candidates`
- `dedup_candidates`

## KudaGo source first run

Manual run inside worker container:

```bash
celery -A apps.worker.worker.celery_app.celery_app call apps.worker.worker.tasks.fetch.fetch_kudago
celery -A apps.worker.worker.celery_app.celery_app call apps.worker.worker.tasks.normalize.normalize_raw_events
celery -A apps.worker.worker.celery_app.celery_app call apps.worker.worker.tasks.enrich.enrich_candidates
celery -A apps.worker.worker.celery_app.celery_app call apps.worker.worker.tasks.dedup.dedup_candidates
```

## Tests

```bash
pytest
```

## Legal notes

- Use source connectors only where API/ToS/robots policy allows data collection.
- Keep source attribution fields (`source_url`, `source_name`) for each event.

## Production checklist (short)

- Configure Sentry and metrics scraping.
- Rotate secrets and move them to secret manager.
- Add queue monitoring and dead-letter queue policy.
- Add periodic DB backup and restore drill.
- Review ToS/robots for each connector before enabling it.
