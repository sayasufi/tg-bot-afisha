from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base


class SourceRun(Base):
    __tablename__ = "source_runs"
    __table_args__ = {"schema": "events"}

    run_id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("ref.sources.source_id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stats_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error_text: Mapped[str] = mapped_column(Text, default="", nullable=False)

    source = relationship("Source", back_populates="runs")
