"""SQLAlchemy ORM model — RunEvent for real-time pipeline logging."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="SEARCH_QUERY | DOWNLOAD | CLASSIFY | CHUNK | EMBED | PROSECUTION | DEFENSE | ARBITER | STATUS | ERROR"
    )
    agent: Mapped[str | None] = mapped_column(
        String(30), nullable=True, comment="discovery | prosecution | defense | arbiter"
    )
    indicator_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Optional JSON payload")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
