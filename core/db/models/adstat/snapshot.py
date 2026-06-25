from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class AdSnapshot(Base):
    """Снимок статистики канала — append-only ряд (строка на (канал, источник, заход))."""

    __tablename__ = "snapshots"
    __table_args__ = (
        Index("ix_adstat_snapshots_channel_captured", "channel_id", "captured_at"),
        Index("ix_adstat_snapshots_source", "source"),
        {"schema": "adstat"},
    )

    snapshot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("adstat.channels.channel_id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    subscribers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    post_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # цена размещения «от», ₽ (Telega.in)
    cpm: Mapped[float | None] = mapped_column(Float, nullable=True)         # цена за 1000 охвата, ₽
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)      # рейтинг канала (Telega)
    er: Mapped[float | None] = mapped_column(Float, nullable=True)
    err: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_reach: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    premium_subs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    month_growth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mentions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_scam: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_boosting: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_stolen: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sanctioned: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
