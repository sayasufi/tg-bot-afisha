"""broadcast campaigns: кастомные paced-рассылки + поюзерный ledger (идемпотентность) + notify_broadcasts

Revision ID: 0046_broadcast_campaigns
Revises: 0045_adstat_target_scraped
Create Date: 2026-06-29

v1: schedule_kind ∈ now|at_utc (at_local/таймзоны отложены — иначе дабл-сенд/потеря юзеров без города).
notify_broadcasts DEFAULT true: существующие вовлечённые юзеры достижимы, опт-аут уважается (см. resolver).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0046_broadcast_campaigns"
down_revision = "0045_adstat_target_scraped"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ref.broadcast_campaigns — одна строка = одна кампания (draft→scheduled→sending→sent/cancelled).
    op.create_table(
        "broadcast_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),                 # HTML (parse_mode=HTML)
        sa.Column("image_url", sa.Text(), nullable=True),             # SSRF-guarded на отправке
        sa.Column("button_label", sa.Text(), nullable=True),
        sa.Column("button_url", sa.Text(), nullable=True),            # https-only, валидируется на create
        # {"kind":"all|opted_in|city|active_since", "cities":[...]?, "since_days":7?}
        sa.Column("audience", postgresql.JSONB(), nullable=False, server_default=sa.text("'{\"kind\":\"opted_in\"}'::jsonb")),
        sa.Column("schedule_kind", sa.Text(), nullable=False, server_default=sa.text("'now'")),  # now | at_utc
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),                    # для at_utc
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # SAFETY-гейты
        sa.Column("test_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatch_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),            # admin-логин (actor), не telegram_id
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="ref",
    )
    op.create_index("ix_broadcast_campaigns_status", "broadcast_campaigns", ["status"], schema="ref")

    # ref.broadcast_recipients — поюзерный журнал = идемпотентность. PK (campaign,user) → не задвоит.
    op.create_table(
        "broadcast_recipients",
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ref.broadcast_campaigns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),  # pending | ok | permanent
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="ref",
    )

    # Отдельный опт-аут для кастомных рассылок (≠ дайджест-подписка). DEFAULT true — мета-операция на PG11+.
    op.add_column("users", sa.Column("notify_broadcasts", sa.Boolean(), nullable=False, server_default=sa.text("true")), schema="ref")


def downgrade() -> None:
    op.drop_column("users", "notify_broadcasts", schema="ref")
    op.drop_table("broadcast_recipients", schema="ref")
    op.drop_index("ix_broadcast_campaigns_status", table_name="broadcast_campaigns", schema="ref")
    op.drop_table("broadcast_campaigns", schema="ref")
