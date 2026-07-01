"""User submissions (ref.pending_submissions) — durable queue for «предложить своё мероприятие /
добавить свой канал», with cheap validation and admin moderation.

APPROVED EVENTS flow into the regular pipeline via events.raw_events under a PER-CITY
`user_submission-<slug>` source (config_json={'city': slug}) so enrich's `city_for_source_config`
geocodes them in the right city — a single global source would send everything to the default city.
The raw carries the structured form fields shaped for RuleBasedNormalizer (no LLM needed), and
normalize applies the same upcoming-window + completeness gates as telegram (see normalize.py).
"""
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.repositories.ingestion import ensure_source, upsert_raw_event
from core.domain.cities import city_by_slug


# ---- Payload shaping (structured form → RuleBasedNormalizer input) -----------

def _event_payload(data: dict) -> dict:
    """Map a vetted event submission to the dict RuleBasedNormalizer.normalize expects.
    startDate/endDate drive its LD-JSON date branch; price is a text field it parses."""
    pmin, pmax = data.get("price_min"), data.get("price_max")
    if pmin is not None and pmax is not None and float(pmax) != float(pmin):
        price = f"{int(float(pmin))}-{int(float(pmax))}"
    elif pmin is not None:
        price = str(int(float(pmin)))
    elif pmax is not None:
        price = str(int(float(pmax)))
    else:
        price = ""
    category = data.get("category")
    return {
        "title": data.get("title") or "",
        "description": data.get("description") or "",
        "startDate": data.get("date_start") or "",
        "endDate": data.get("date_end") or None,
        "venue": data.get("venue") or "",
        "address": data.get("address") or "",
        "price": price,
        "is_free": bool(data.get("is_free")),
        "url": data.get("url") or "",
        "image": data.get("image") or "",
        "categories": [category] if category else [],
        "user_submission": True,
    }


def _event_raw_text(data: dict) -> str:
    place = " ".join(p for p in [data.get("venue") or "", data.get("address") or ""] if p)
    parts = [data.get("title") or "", data.get("description") or "", place]
    return "\n\n".join(p for p in parts if p).strip() or (data.get("title") or "событие")


# ---- CRUD -------------------------------------------------------------------

async def create_submission(
    db: AsyncSession,
    *,
    kind: str,
    data: dict,
    submitted_by: int,
    submitted_username: str | None,
    city_slug: str | None,
    status: str = "needs_review",
    checks: dict | None = None,
) -> str:
    """Insert a submission, return its id (str UUID). No side effects on events/channels."""
    sid = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO ref.pending_submissions "
            "(submission_id, kind, status, data, checks, submitted_by, submitted_username, city_slug) "
            "VALUES (:sid, :kind, :status, CAST(:data AS jsonb), CAST(:checks AS jsonb), :by, :uname, :city)"
        ),
        {
            "sid": sid, "kind": kind, "status": status,
            "data": json.dumps(data, ensure_ascii=False),
            "checks": json.dumps(checks or {}, ensure_ascii=False),
            "by": int(submitted_by), "uname": submitted_username, "city": city_slug,
        },
    )
    await db.commit()
    return sid


async def count_user_submissions_today(db: AsyncSession, submitted_by: int) -> int:
    """Durable per-user daily cap fallback (the Redis counter is the fast path)."""
    return int((await db.execute(
        text(
            "SELECT count(*) FROM ref.pending_submissions "
            "WHERE submitted_by = :by AND created_at > now() - interval '1 day'"
        ),
        {"by": int(submitted_by)},
    )).scalar() or 0)


async def get_submission(db: AsyncSession, submission_id: str) -> dict | None:
    row = (await db.execute(
        text(
            "SELECT submission_id, kind, status, data, checks, submitted_by, submitted_username, "
            "city_slug, reject_code, target_raw_id, target_event_id, created_at "
            "FROM ref.pending_submissions WHERE submission_id = :sid"
        ),
        {"sid": submission_id},
    )).mappings().first()
    return dict(row) if row else None


async def list_submissions(
    db: AsyncSession, *, status: str | None, kind: str | None, limit: int, offset: int
) -> list[dict]:
    clauses, params = [], {"limit": limit, "offset": offset}
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if kind:
        clauses.append("kind = :kind")
        params["kind"] = kind
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = (await db.execute(
        text(
            "SELECT submission_id, kind, status, data, checks, submitted_by, submitted_username, "
            "city_slug, reject_code, created_at "
            "FROM ref.pending_submissions" + where + " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    )).mappings().all()
    return [dict(r) for r in rows]


async def count_submissions(db: AsyncSession, *, status: str | None, kind: str | None) -> int:
    clauses, params = [], {}
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if kind:
        clauses.append("kind = :kind")
        params["kind"] = kind
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return int((await db.execute(
        text("SELECT count(*) FROM ref.pending_submissions" + where), params
    )).scalar() or 0)


# ---- Approve / reject -------------------------------------------------------

async def ingest_event_submission(db: AsyncSession, submission: dict) -> int:
    """Approved event → events.raw_events under the per-city user source, then the regular pipeline
    (normalize → enrich → dedup) handles geocoding/category/dedup. Returns the raw_id."""
    city = city_by_slug(submission.get("city_slug") or "moscow")
    source = await ensure_source(
        db, name=f"user_submission-{city.slug}", kind="user_submission", base_url="",
        config_json={"city": city.slug},
    )
    raw = await upsert_raw_event(
        db,
        source_id=source.source_id,
        external_id=f"sub:{submission['submission_id']}",
        payload=_event_payload(submission["data"]),
        raw_text=_event_raw_text(submission["data"]),
    )
    return raw.raw_id


async def approve_channel_submission(db: AsyncSession, submission: dict) -> int | None:
    """Approved channel → ref.telegram_channels via the case-insensitive admin path (SELECT LOWER(username)
    → UPDATE-on-hit / INSERT-on-miss), NOT a seed ON CONFLICT (usernames are mixed-case → dupes). is_active
    so the NEXT fetch-telegram cycle picks it up (no synchronous fetch trigger). Returns the channel_id."""
    data = submission.get("data") or {}
    uname = (data.get("username_norm") or "").strip().lower()
    if not uname:
        return None
    city = city_by_slug(submission.get("city_slug") or "moscow")
    city_id = city.city_id or 1  # city_id is NOT NULL; every active city has one, fall back to Moscow
    existing = (await db.execute(
        text("SELECT channel_id FROM ref.telegram_channels WHERE LOWER(username) = :u"), {"u": uname}
    )).first()
    if existing:
        cid = existing[0]
        await db.execute(
            text("UPDATE ref.telegram_channels SET city_id = :c, is_active = true WHERE channel_id = :id"),
            {"c": city_id, "id": cid},
        )
    else:
        row = (await db.execute(
            text(
                "INSERT INTO ref.telegram_channels (username, city_id, is_active) "
                "VALUES (:u, :c, true) RETURNING channel_id"
            ),
            {"u": uname, "c": city_id},
        )).first()
        cid = row[0] if row else None
    await db.commit()
    return cid


async def set_status(
    db: AsyncSession,
    submission_id: str,
    status: str,
    *,
    reviewed_by: str | None = None,
    reject_code: str | None = None,
    target_raw_id: int | None = None,
    target_event_id: str | None = None,
    target_channel_id: int | None = None,
) -> None:
    await db.execute(
        text(
            "UPDATE ref.pending_submissions SET status = :status, updated_at = :now, "
            "reviewed_by = COALESCE(:rev, reviewed_by), "
            "reviewed_at = CASE WHEN :rev IS NULL THEN reviewed_at ELSE :now END, "
            "reject_code = COALESCE(:rc, reject_code), "
            "target_raw_id = COALESCE(:raw, target_raw_id), "
            "target_event_id = COALESCE(CAST(:eid AS uuid), target_event_id), "
            "target_channel_id = COALESCE(:chid, target_channel_id) "
            "WHERE submission_id = :sid"
        ),
        {
            "status": status, "now": datetime.now(timezone.utc), "rev": reviewed_by,
            "rc": reject_code, "raw": target_raw_id, "eid": target_event_id,
            "chid": target_channel_id, "sid": submission_id,
        },
    )
    await db.commit()
