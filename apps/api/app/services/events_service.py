from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from geoalchemy2 import Geography, Geometry
from sqlalchemy import Select, and_, bindparam, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import Event, EventOccurrence, Venue


class EventQueryService:
    def __init__(self, db: AsyncSession):
        self.db = db

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

    # At/above this zoom the map returns individual pins; below it, the server
    # returns grid-aggregated clusters so payload/marker count don't grow with the
    # total number of events.
    _DETAIL_ZOOM = 14

    @staticmethod
    def _bbox_clause(bbox: tuple[float, float, float, float]):
        min_lon, min_lat, max_lon, max_lat = bbox
        return text(
            "ST_Intersects(venues.geom::geometry, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326))"
        ).bindparams(
            bindparam("min_lon", min_lon),
            bindparam("min_lat", min_lat),
            bindparam("max_lon", max_lon),
            bindparam("max_lat", max_lat),
        )

    async def map_events(
        self,
        bbox: tuple[float, float, float, float] | None,
        date_from: datetime | None,
        date_to: datetime | None,
        categories: list[str] | None,
        price_min: float | None,
        price_max: float | None,
        q: str | None,
        limit: int | None,
        offset: int,
        zoom: int | None = None,
    ):
        # "Показать N" = filter-wide count of map-able events (stable while panning).
        total = await self._count_pinnable(date_from, date_to, categories, price_min, price_max, q)
        if zoom is not None and bbox is not None and zoom < self._DETAIL_ZOOM:
            clusters = await self._cluster(bbox, zoom, date_from, date_to, categories, price_min, price_max, q)
            return {"clusters": clusters, "items": [], "total": total}
        items = await self._detail(bbox, date_from, date_to, categories, price_min, price_max, q, limit, offset)
        return {"clusters": [], "items": items, "total": total}

    async def _count_pinnable(self, date_from, date_to, categories, price_min, price_max, q) -> int:
        stmt = (
            select(func.count(func.distinct(Event.event_id)))
            .select_from(Event)
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .join(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active", Venue.geom.is_not(None))
        )
        stmt = self._apply_filters(stmt, date_from, date_to, categories, price_min, price_max, q)
        return int(await self.db.scalar(stmt) or 0)

    async def _cluster(self, bbox, zoom, date_from, date_to, categories, price_min, price_max, q):
        # One representative point per event (soonest occurrence's venue) within the
        # viewport, then snap to a zoom-sized grid and aggregate to cluster centroids.
        inner = (
            select(Event.event_id.label("eid"), cast(Venue.geom, Geometry).label("g"), EventOccurrence.date_start.label("ds"))
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .join(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active", Venue.geom.is_not(None))
        )
        inner = self._apply_filters(inner, date_from, date_to, categories, price_min, price_max, q)
        inner = (
            inner.where(self._bbox_clause(bbox))
            .distinct(Event.event_id)
            .order_by(Event.event_id, EventOccurrence.date_start.asc())
            .subquery()
        )
        cell = 90.0 / (2 ** zoom)  # grid cell in degrees (~one cluster per ~80 screen px)
        grid = func.ST_SnapToGrid(inner.c.g, cell, cell)
        stmt = (
            select(
                func.count().label("cnt"),
                func.ST_Y(func.ST_Centroid(func.ST_Collect(inner.c.g))).label("lat"),
                func.ST_X(func.ST_Centroid(func.ST_Collect(inner.c.g))).label("lon"),
            )
            .select_from(inner)
            .group_by(grid)
        )
        rows = (await self.db.execute(stmt)).all()
        return [
            {"id": f"c{i}", "lat": float(lat), "lon": float(lon), "count": int(cnt)}
            for i, (cnt, lat, lon) in enumerate(rows)
            if lat is not None and lon is not None
        ]

    async def _detail(self, bbox, date_from, date_to, categories, price_min, price_max, q, limit, offset):
        # Compute venue lat/lon in the main query (was an N+1 per-row subquery).
        lat_col = func.ST_Y(cast(Venue.geom, Geometry)).label("lat")
        lon_col = func.ST_X(cast(Venue.geom, Geometry)).label("lon")
        stmt = (
            select(Event, EventOccurrence, Venue.name.label("venue_name"), Venue.hours_json.label("venue_hours"), lat_col, lon_col)
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active")
        )
        stmt = self._apply_filters(stmt, date_from, date_to, categories, price_min, price_max, q)
        if bbox:
            stmt = stmt.where(Venue.geom.is_not(None)).where(self._bbox_clause(bbox))
        # One row per event — the soonest in-window occurrence — so an event with
        # several showtimes (e.g. 16 & 23 June) shows a single pin, not one per date.
        stmt = stmt.distinct(Event.event_id).order_by(Event.event_id, EventOccurrence.date_start.asc())
        rows = (await self.db.execute(stmt.limit(limit).offset(offset))).all()
        items = [
            {
                "event_id": event.event_id,
                "title": event.canonical_title,
                "category": event.category,
                "date_start": occ.date_start,
                "date_end": occ.date_end,
                "price_min": occ.price_min,
                "venue": venue_name,
                "venue_hours": venue_hours,
                "lat": float(lat) if lat is not None else None,
                "lon": float(lon) if lon is not None else None,
                "primary_image_url": event.cached_image_url or event.primary_image_url,
            }
            for event, occ, venue_name, venue_hours, lat, lon in rows
        ]
        # DISTINCT ON forces event_id ordering; present pins by soonest date instead.
        items.sort(key=lambda it: it["date_start"])
        return items

    async def event_detail(self, event_id: UUID):
        event = await self.db.get(Event, event_id)
        if not event:
            return None
        rows = (await self.db.execute(
            select(
                EventOccurrence,
                Venue.name.label("venue_name"),
                Venue.address.label("venue_address"),
                Venue.hours_json.label("venue_hours"),
                func.ST_Y(cast(Venue.geom, Geometry)).label("lat"),
                func.ST_X(cast(Venue.geom, Geometry)).label("lon"),
            )
            .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(EventOccurrence.event_id == event_id)
            .order_by(EventOccurrence.date_start.asc())
        )).all()
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
                "venue_hours": venue_hours,
                "lat": float(lat) if lat is not None else None,
                "lon": float(lon) if lon is not None else None,
            }
            for occ, venue_name, venue_address, venue_hours, lat, lon in rows
        ]
        return {
            "event_id": event.event_id,
            "canonical_title": event.canonical_title,
            "canonical_description": event.canonical_description,
            "category": event.category,
            "subcategory": event.subcategory,
            "age_limit": event.age_limit,
            "primary_image_url": event.cached_image_url or event.primary_image_url,
            "occurrences": occurrences,
        }

    async def nearby(
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
        # Distance + coords computed in the main query (was an N+1: 2-3 extra queries/row).
        dist_col = func.ST_Distance(Venue.geom, point).label("distance_m")
        lat_col = func.ST_Y(cast(Venue.geom, Geometry)).label("lat")
        lon_col = func.ST_X(cast(Venue.geom, Geometry)).label("lon")
        stmt = (
            select(Event, EventOccurrence, Venue.name.label("venue_name"), dist_col, lat_col, lon_col)
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .join(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active")
        )
        stmt = self._apply_filters(stmt, date_from, date_to, categories, None, None, q)
        stmt = (
            stmt.where(Venue.geom.is_not(None))
            .where(func.ST_DWithin(Venue.geom, point, radius_m))
            .order_by(dist_col.asc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).all()
        result = [
            {
                "event_id": event.event_id,
                "title": event.canonical_title,
                "category": event.category,
                "distance_m": float(distance or 0.0),
                "date_start": occ.date_start,
                "price_min": occ.price_min,
                "venue": venue_name,
                "lat": float(lat) if lat is not None else None,
                "lon": float(lon) if lon is not None else None,
            }
            for event, occ, venue_name, distance, lat, lon in rows
        ]
        return {"items": result}

    async def categories(self):
        rows = (await self.db.execute(select(Event.category).distinct().order_by(Event.category.asc()))).scalars().all()
        return {"categories": rows}

    async def search(self, q: str, city: str | None, limit: int):
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

        rows = (await self.db.execute(stmt)).all()
        return {"items": [{"event_id": row[0], "title": row[1], "score": float(row[2] or 0)} for row in rows]}
