"""normalize Moscow city labels

Revision ID: 0037_normalize_moscow_city
Revises: 0036_telegram_channel_subscribers
Create Date: 2026-06-25
"""
from alembic import op


revision = "0037_normalize_moscow_city"
down_revision = "0036_channel_subscribers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            canonical_id integer;
            duplicate_id integer;
        BEGIN
            SELECT city_id INTO canonical_id
            FROM ref.cities
            WHERE name = 'Moscow' AND country = 'RU'
            ORDER BY city_id
            LIMIT 1;

            IF canonical_id IS NULL THEN
                SELECT city_id INTO canonical_id
                FROM ref.cities
                WHERE name = 'Москва' AND country = 'RU'
                ORDER BY city_id
                LIMIT 1;
            END IF;

            IF canonical_id IS NULL THEN
                INSERT INTO ref.cities (name, country, timezone)
                VALUES ('Москва', 'RU', 'Europe/Moscow')
                RETURNING city_id INTO canonical_id;
            END IF;

            FOR duplicate_id IN
                SELECT city_id
                FROM ref.cities
                WHERE country = 'RU'
                  AND name IN ('Moscow', 'Москва')
                  AND city_id <> canonical_id
            LOOP
                UPDATE ref.telegram_channels SET city_id = canonical_id WHERE city_id = duplicate_id;
                UPDATE ref.map_places SET city_id = canonical_id WHERE city_id = duplicate_id;
                DELETE FROM ref.cities WHERE city_id = duplicate_id;
            END LOOP;

            UPDATE ref.cities
            SET name = 'Москва', timezone = 'Europe/Moscow'
            WHERE city_id = canonical_id;
        END $$;
        """
    )
    op.execute("UPDATE events.venues SET city = 'Москва', updated_at = now() WHERE city = 'Moscow'")


def downgrade() -> None:
    op.execute("UPDATE ref.cities SET name = 'Moscow' WHERE city_id = 1 AND name = 'Москва'")
