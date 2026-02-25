from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base
from core.db.models.mixins import TimestampMixin


class Source(Base, TimestampMixin):
    __tablename__ = "sources"

    source_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    crawl_interval_sec: Mapped[int] = mapped_column(Integer, default=900, nullable=False)
    robots_policy: Mapped[str] = mapped_column(Text, default="", nullable=False)

    raw_events = relationship("RawEvent", back_populates="source")
    runs = relationship("SourceRun", back_populates="source")
