from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class IngestInbox(Base):
    __tablename__ = "ingest_inbox"

    inbox_id: Mapped[int] = mapped_column(primary_key=True)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
