# tg-bot-afisha MVP

MVP Telegram bot + Telegram Mini App for discovering nearby events from multiple sources.

## Stack

- Backend: FastAPI + SQLAlchemy + Alembic
- Worker: Prefect 3 + Redis
- DB: PostgreSQL + PostGIS
- Bot: aiogram 3
- Mini App: React + Vite + Leaflet / MapLibre

## Architecture

Layered monorepo. The dependency rule points **one way and down** —
`apps → pipeline / connectors → core`. `core` never imports upward, and the
four services under `apps/` never import each other; anything two services
share lives in `core` (e.g. card/caption rendering in `core/render`).

**`apps/` — isolated services** (each its own container, no cross-service imports):
- `apps/api`: public REST API for bot + miniapp (FastAPI, `uvicorn apps.api.main:app`)
- `apps/bot`: Telegram bot — city selection, search, Mini App launch (aiogram 3)
- `apps/worker`: ingestion/enrichment orchestration (Prefect flows in `flows.py`, logic in `tasks/`); pipeline is `fetch → normalize → enrich → dedup`
- `apps/adstat`: ad-channel research domain (models + service in one place; gated by `ADSTAT_ENABLED`)

**`connectors/` — source plugins** (`web/`: KudaGo, Yandex Afisha, Afisha.ru, Timepad; `telegram/`)

**`pipeline/` — stateless processing** (`normalizer`, `geocoding`, `llm`, `maintenance`)

**`core/` — foundation** (imports nothing from the layers above):
- `config` settings · `db` models+repositories · `contracts` cross-layer dataclasses
- `domain` (cities, categorization, public codes) · `infra` (redis, SSRF-safe http)
- `services` (invite tokens, LLM concurrency limiter) · `matching` (dedup algorithms)
- `render` (poster cards + bot captions) · `media` · `search` · `logging`

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
