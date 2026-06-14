from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from geoalchemy2 import Geography, Geometry
from sqlalchemy import Select, and_, bindparam, cast, func, or_, select, text
from sqlalchemy.orm import Session

from core.db.models import Event, EventOccurrence, Venue


class EventQueryService:
    def __init__(self, db: Session):
        self.db = db

    def _base_stmt(self):
        return (
            select(Event, EventOccurrence, Venue)
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active")
        )

    def _apply_filters(
        self,
        stmt: Select[Any],
        date_from: datetime | None,
        date_to: datetime | None,
        categories: list[str] | None,
        price_min: float | None,
        price_max: float | None,
        q: str | None,
    ):
        filters = []
        # Hide events that have already ENDED. An occurrence is "active" from
        # `floor` onward if it ends at/after the floor (ongoing exhibitions whose
        # start is in the past are kept; truly finished events drop out). Default
        # floor is the start of today, so the map never shows past events.
        floor = date_from or datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        filters.append(func.coalesce(EventOccurrence.date_end, EventOccurrence.date_start) >= floor)
        if date_to:
            filters.append(EventOccurrence.date_start <= date_to)
        if categories:
            filters.append(Event.category.in_(categories))
        if price_min is not None:
            filters.append(or_(EventOccurrence.price_min.is_(None), EventOccurrence.price_min >= price_min))
        if price_max is not None:
            filters.append(or_(EventOccurrence.price_max.is_(None), EventOccurrence.price_max <= price_max))
        if q:
            filters.append(
                or_(
                    Event.canonical_title.ilike(f"%{q}%"),
                    Event.canonical_description.ilike(f"%{q}%"),
                )
            )
        if filters:
            stmt = stmt.where(and_(*filters))
        return stmt

    def map_events(
        self,
        bbox: tuple[float, float, float, float] | None,
        date_from: datetime | None,
        date_to: datetime | None,
        categories: list[str] | None,
        price_min: float | None,
        price_max: float | None,
        q: str | None,
        limit: int,
        offset: int,
    ):
        # Compute venue lat/lon in the main query (was an N+1 per-row subquery).
        lat_col = func.ST_Y(cast(Venue.geom, Geometry)).label("lat")
        lon_col = func.ST_X(cast(Venue.geom, Geometry)).label("lon")
        stmt = (
            select(Event, EventOccurrence, Venue.name.label("venue_name"), lat_col, lon_col)
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active")
        )
        stmt = self._apply_filters(stmt, date_from, date_to, categories, price_min, price_max, q)
        if bbox:
            min_lon, min_lat, max_lon, max_lat = bbox
            stmt = (
                stmt.where(Venue.geom.is_not(None))
                .where(
                    text(
                        "ST_Intersects(venues.geom::geometry, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326))"
                    ).bindparams(
                        bindparam("min_lon", min_lon),
                        bindparam("min_lat", min_lat),
                        bindparam("max_lon", max_lon),
                        bindparam("max_lat", max_lat),
                    )
                )
            )

        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

        rows = self.db.execute(stmt.order_by(EventOccurrence.date_start.asc()).limit(limit).offset(offset)).all()
        items = [
            {
                "event_id": event.event_id,
                "title": event.canonical_title,
                "category": event.category,
                "date_start": occ.date_start,
                "date_end": occ.date_end,
                "price_min": occ.price_min,
                "venue": venue_name,
                "lat": float(lat) if lat is not None else None,
                "lon": float(lon) if lon is not None else None,
                "primary_image_url": event.primary_image_url,
            }
            for event, occ, venue_name, lat, lon in rows
        ]

        # The client clusters on the fly (react-leaflet-cluster); the server-side
        # cluster list is unused, so we skip that query entirely.
        return {"clusters": [], "items": items, "total": total}

    def event_detail(self, event_id: UUID):
        event = self.db.get(Event, event_id)
        if not event:
            return None
        rows = self.db.execute(
            select(
                EventOccurrence,
                Venue.name.label("venue_name"),
                Venue.address.label("venue_address"),
                func.ST_Y(cast(Venue.geom, Geometry)).label("lat"),
                func.ST_X(cast(Venue.geom, Geometry)).label("lon"),
            )
            .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(EventOccurrence.event_id == event_id)
            .order_by(EventOccurrence.date_start.asc())
        ).all()
        occurrences = [
            {
                "occurrence_id": occ.occurrence_id,
                "date_start": occ.date_start,
                "date_end": occ.date_end,
                "price_min": occ.price_min,
                "price_max": occ.price_max,
                "currency": occ.currency,
                "source_best_url": occ.source_best_url,
                "venue": venue_name,
                "address": venue_address,
                "lat": float(lat) if lat is not None else None,
                "lon": float(lon) if lon is not None else None,
            }
            for occ, venue_name, venue_address, lat, lon in rows
        ]
        return {
            "event_id": event.event_id,
            "canonical_title": event.canonical_title,
            "canonical_description": event.canonical_description,
            "category": event.category,
            "subcategory": event.subcategory,
            "age_limit": event.age_limit,
            "primary_image_url": event.primary_image_url,
            "occurrences": occurrences,
        }

    def nearby(
        self,
        lat: float,
        lon: float,
        radius_m: int,
        date_from: datetime | None,
        date_to: datetime | None,
        categories: list[str] | None,
        q: str | None,
        limit: int,
    ):
        # Cast to geography so ST_DWithin/ST_Distance use meters, not degrees.
        point = cast(func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326), Geography(geometry_type="POINT", srid=4326))
        stmt = self._apply_filters(self._base_stmt(), date_from, date_to, categories, None, None, q)
        stmt = stmt.where(Venue.geom.is_not(None)).where(func.ST_DWithin(Venue.geom, point, radius_m)).limit(limit)
        rows = self.db.execute(stmt).all()

        result = []
        for event, occ, venue in rows:
            distance = self.db.scalar(select(func.ST_Distance(venue.geom, point))) if venue and venue.geom is not None else 0.0
            v_lat = v_lon = None
            if venue and venue.geom is not None:
                row = self.db.execute(
                    text(
                        "SELECT ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon FROM events.venues WHERE venue_id = :vid"
                    ),
                    {"vid": venue.venue_id},
                ).mappings().first()
                if row:
                    v_lat = float(row["lat"])
                    v_lon = float(row["lon"])
            result.append(
                {
                    "event_id": event.event_id,
                    "title": event.canonical_title,
                    "category": event.category,
                    "distance_m": float(distance or 0.0),
                    "date_start": occ.date_start,
                    "price_min": occ.price_min,
                    "venue": venue.name if venue else None,
                    "lat": v_lat,
                    "lon": v_lon,
                }
            )
        result.sort(key=lambda x: x["distance_m"])
        return {"items": result}

    def categories(self):
        rows = self.db.execute(select(Event.category).distinct().order_by(Event.category.asc())).scalars().all()
        return {"categories": rows}

    def search(self, q: str, city: str | None, limit: int):
        score = func.similarity(Event.canonical_title, bindparam("q", q))
        stmt = (
            select(Event.event_id, Event.canonical_title, score.label("score"))
            .where(Event.status == "active")
            .where(or_(Event.canonical_title.ilike(f"%{q}%"), Event.canonical_description.ilike(f"%{q}%")))
            .order_by(text("score DESC"))
            .limit(limit)
        )

        if city:
            stmt = (
                select(Event.event_id, Event.canonical_title, score.label("score"))
                .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
                .join(Venue, Venue.venue_id == EventOccurrence.venue_id)
                .where(Event.status == "active")
                .where(Venue.city.ilike(city))
                .where(or_(Event.canonical_title.ilike(f"%{q}%"), Event.canonical_description.ilike(f"%{q}%")))
                .distinct()
                .order_by(text("score DESC"))
                .limit(limit)
            )

        rows = self.db.execute(stmt).all()
        return {"items": [{"event_id": row[0], "title": row[1], "score": float(row[2] or 0)} for row in rows]}
