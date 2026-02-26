"""initial schema with ref/events split

Revision ID: 0001_init
Revises:
Create Date: 2026-02-26
"""

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geography


revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE SCHEMA IF NOT EXISTS ref")
    op.execute("CREATE SCHEMA IF NOT EXISTS events")

    op.create_table(
        "cities",
        sa.Column("city_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("country", sa.String(8), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("center", Geography(geometry_type="POINT", srid=4326), nullable=True),
        sa.UniqueConstraint("name", "country", name="uq_city_name_country"),
        schema="ref",
    )
    op.create_index("ix_cities_center", "cities", ["center"], schema="ref", postgresql_using="gist")

    op.create_table(
        "sources",
        sa.Column("source_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("crawl_interval_sec", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("robots_policy", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="ref",
    )

    op.create_table(
        "users",
        sa.Column("telegram_user_id", sa.BigInteger(), primary_key=True),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("ref.cities.city_id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="ref",
    )

    op.create_table(
        "telegram_channels",
        sa.Column("channel_id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(255), nullable=False, unique=True),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("ref.cities.city_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="ref",
    )
    op.create_index("ix_telegram_channels_city_id", "telegram_channels", ["city_id"], schema="ref")

    op.create_table(
        "source_runs",
        sa.Column("run_id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("ref.sources.source_id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stats_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("error_text", sa.Text(), nullable=False, server_default=""),
        schema="events",
    )

    op.create_table(
        "raw_events",
        sa.Column("raw_id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("ref.sources.source_id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("raw_payload_json", sa.JSON(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("source_id", "external_id", name="uq_raw_source_external"),
        schema="events",
    )
    op.create_index("ix_raw_content_hash", "raw_events", ["content_hash"], schema="events")
    op.create_index("ix_raw_fetched_at", "raw_events", ["fetched_at"], schema="events")

    op.create_table(
        "event_candidates",
        sa.Column("candidate_id", sa.Integer(), primary_key=True),
        sa.Column("raw_id", sa.Integer(), sa.ForeignKey("events.raw_events.raw_id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("date_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("venue", sa.String(255), nullable=False, server_default=""),
        sa.Column("address", sa.String(500), nullable=False, server_default=""),
        sa.Column("price_min", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_max", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="RUB"),
        sa.Column("age_limit", sa.String(32), nullable=False, server_default=""),
        sa.Column("tags_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("images_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("parse_confidence", sa.Numeric(4, 2), nullable=False, server_default="0.5"),
        schema="events",
    )

    op.create_table(
        "venues",
        sa.Column("venue_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("address", sa.String(500), nullable=False, server_default=""),
        sa.Column("city", sa.String(120), nullable=False, server_default=""),
        sa.Column("country", sa.String(8), nullable=False, server_default=""),
        sa.Column("geom", Geography(geometry_type="POINT", srid=4326), nullable=True),
        sa.Column("geocode_provider", sa.String(32), nullable=False, server_default=""),
        sa.Column("geocode_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", "address", name="uq_venue_name_address"),
        schema="events",
    )
    op.create_index("ix_venues_geom", "venues", ["geom"], schema="events", postgresql_using="gist")

    op.create_table(
        "events",
        sa.Column("event_id", sa.UUID(), primary_key=True),
        sa.Column("canonical_title", sa.String(500), nullable=False),
        sa.Column("canonical_description", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(64), nullable=False, server_default="other"),
        sa.Column("subcategory", sa.String(64), nullable=False, server_default=""),
        sa.Column("age_limit", sa.String(32), nullable=False, server_default=""),
        sa.Column("popularity_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rating_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("primary_image_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="events",
    )
    op.execute(
        "CREATE INDEX ix_events_title_trgm ON events.events USING gin (canonical_title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_events_desc_trgm ON events.events USING gin (canonical_description gin_trgm_ops)"
    )

    op.create_table(
        "event_occurrences",
        sa.Column("occurrence_id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.UUID(), sa.ForeignKey("events.events.event_id", ondelete="CASCADE"), nullable=False),
        sa.Column("venue_id", sa.Integer(), sa.ForeignKey("events.venues.venue_id", ondelete="SET NULL"), nullable=True),
        sa.Column("date_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("date_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price_min", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_max", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="RUB"),
        sa.Column("source_best_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="events",
    )
    op.create_index("ix_occurrences_date_start", "event_occurrences", ["date_start"], schema="events")
    op.create_index("ix_occurrences_event", "event_occurrences", ["event_id"], schema="events")

    op.create_table(
        "event_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.UUID(), sa.ForeignKey("events.events.event_id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("ref.sources.source_id", ondelete="CASCADE"), nullable=False),
        sa.Column("raw_id", sa.Integer(), sa.ForeignKey("events.raw_events.raw_id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_event_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("raw_id", name="uq_event_sources_raw_id"),
        schema="events",
    )

    op.execute(
        """
        INSERT INTO ref.cities (name, country, timezone)
        VALUES ('Moscow', 'RU', 'Europe/Moscow')
        ON CONFLICT (name, country) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO ref.telegram_channels (username, city_id, is_active)
        SELECT 'kuda_v_moskva', city_id, true
        FROM ref.cities
        WHERE name = 'Moscow' AND country = 'RU'
        ON CONFLICT (username) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("event_sources", schema="events")
    op.drop_index("ix_occurrences_event", table_name="event_occurrences", schema="events")
    op.drop_index("ix_occurrences_date_start", table_name="event_occurrences", schema="events")
    op.drop_table("event_occurrences", schema="events")
    op.execute("DROP INDEX IF EXISTS events.ix_events_desc_trgm")
    op.execute("DROP INDEX IF EXISTS events.ix_events_title_trgm")
    op.drop_table("events", schema="events")
    op.drop_index("ix_venues_geom", table_name="venues", schema="events")
    op.drop_table("venues", schema="events")
    op.drop_table("event_candidates", schema="events")
    op.drop_index("ix_raw_fetched_at", table_name="raw_events", schema="events")
    op.drop_index("ix_raw_content_hash", table_name="raw_events", schema="events")
    op.drop_table("raw_events", schema="events")
    op.drop_table("source_runs", schema="events")
    op.drop_index("ix_telegram_channels_city_id", table_name="telegram_channels", schema="ref")
    op.drop_table("telegram_channels", schema="ref")
    op.drop_table("users", schema="ref")
    op.drop_index("ix_cities_center", table_name="cities", schema="ref")
    op.drop_table("cities", schema="ref")
    op.drop_table("sources", schema="ref")
    op.execute("DROP SCHEMA IF EXISTS events")
    op.execute("DROP SCHEMA IF EXISTS ref")
