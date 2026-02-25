from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, bindparam, func, literal_column, or_, select, text
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
        if date_from:
            filters.append(EventOccurrence.date_start >= date_from)
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
        stmt = self._apply_filters(self._base_stmt(), date_from, date_to, categories, price_min, price_max, q)
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
        items = []
        for event, occ, venue in rows:
            lat = lon = None
            if venue and venue.geom is not None:
                row = self.db.execute(
                    text(
                        "SELECT ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon FROM venues WHERE venue_id = :vid"
                    ),
                    {"vid": venue.venue_id},
                ).mappings().first()
                if row:
                    lat = float(row["lat"])
                    lon = float(row["lon"])
            items.append(
                {
                    "event_id": event.event_id,
                    "title": event.canonical_title,
                    "category": event.category,
                    "date_start": occ.date_start,
                    "price_min": occ.price_min,
                    "venue": venue.name if venue else None,
                    "lat": lat,
                    "lon": lon,
                }
            )

        cluster_rows = self.db.execute(
            text(
                """
                SELECT
                  ROUND(CAST(ST_Y(geom::geometry) AS numeric), 2) AS lat,
                  ROUND(CAST(ST_X(geom::geometry) AS numeric), 2) AS lon,
                  COUNT(*) AS count
                FROM venues
                WHERE geom IS NOT NULL
                GROUP BY 1,2
                LIMIT 100
                """
            )
        ).mappings().all()
        clusters = [
            {
                "id": f"{row['lat']}_{row['lon']}",
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "count": int(row["count"]),
            }
            for row in cluster_rows
        ]
        return {"clusters": clusters, "items": items, "total": total}

    def event_detail(self, event_id: UUID):
        event = self.db.get(Event, event_id)
        if not event:
            return None
        rows = (
            self.db.execute(
                select(EventOccurrence, Venue)
                .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
                .where(EventOccurrence.event_id == event_id)
                .order_by(EventOccurrence.date_start.asc())
            )
            .all()
        )
        occurrences = []
        for occ, venue in rows:
            lat = lon = None
            if venue and venue.geom is not None:
                row = self.db.execute(
                    text(
                        "SELECT ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon FROM venues WHERE venue_id = :vid"
                    ),
                    {"vid": venue.venue_id},
                ).mappings().first()
                if row:
                    lat = float(row["lat"])
                    lon = float(row["lon"])
            occurrences.append(
                {
                    "occurrence_id": occ.occurrence_id,
                    "date_start": occ.date_start,
                    "date_end": occ.date_end,
                    "price_min": occ.price_min,
                    "price_max": occ.price_max,
                    "currency": occ.currency,
                    "source_best_url": occ.source_best_url,
                    "venue": venue.name if venue else None,
                    "address": venue.address if venue else None,
                    "lat": lat,
                    "lon": lon,
                }
            )
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
        point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
        stmt = self._apply_filters(self._base_stmt(), date_from, date_to, categories, None, None, q)
        stmt = stmt.where(Venue.geom.is_not(None)).where(func.ST_DWithin(Venue.geom, point, radius_m)).limit(limit)
        rows = self.db.execute(stmt).all()

        result = []
        for event, occ, venue in rows:
            distance = self.db.scalar(select(func.ST_Distance(venue.geom, point))) if venue and venue.geom is not None else 0.0
            result.append(
                {
                    "event_id": event.event_id,
                    "title": event.canonical_title,
                    "distance_m": float(distance or 0.0),
                    "date_start": occ.date_start,
                }
            )
        result.sort(key=lambda x: x["distance_m"])
        return {"items": result}

    def categories(self):
        rows = self.db.execute(select(Event.category).distinct().order_by(Event.category.asc())).scalars().all()
        return {"categories": rows}

    def search(self, q: str, city: str | None, limit: int):
        score = literal_column("similarity(canonical_title, :q)")
        stmt = (
            select(Event.event_id, Event.canonical_title, score.label("score"))
            .where(or_(Event.canonical_title.ilike(f"%{q}%"), Event.canonical_description.ilike(f"%{q}%")))
            .order_by(text("score DESC"))
            .limit(limit)
            .params(q=q)
        )

        if city:
            stmt = (
                select(Event.event_id, Event.canonical_title, score.label("score"))
                .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
                .join(Venue, Venue.venue_id == EventOccurrence.venue_id)
                .where(Venue.city.ilike(city))
                .where(or_(Event.canonical_title.ilike(f"%{q}%"), Event.canonical_description.ilike(f"%{q}%")))
                .order_by(text("score DESC"))
                .limit(limit)
                .params(q=q)
            )

        rows = self.db.execute(stmt).all()
        return {"items": [{"event_id": row[0], "title": row[1], "score": float(row[2] or 0)} for row in rows]}
