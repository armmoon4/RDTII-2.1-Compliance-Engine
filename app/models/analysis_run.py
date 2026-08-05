"""SQLAlchemy ORM model — AnalysisRun tracks a top-level analysis job."""
import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import DateTime, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RunStatus(str, PyEnum):
    QUEUED = "QUEUED"
    DISCOVERING = "DISCOVERING"
    ANALYSING = "ANALYSING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    country: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus), default=RunStatus.QUEUED, nullable=False
    )
    pillar_ids_requested: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="Comma-separated pillar IDs, NULL = all"
    )
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="gemini | openai | ollama | auto"
    )
    current_activity: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_indicators: Mapped[int] = mapped_column(default=0)
    completed_indicators: Mapped[int] = mapped_column(default=0)
    total_input_tokens: Mapped[int | None] = mapped_column(
        default=None, nullable=True, comment="Cumulative input tokens burned by LLM calls"
    )
    total_output_tokens: Mapped[int | None] = mapped_column(
        default=None, nullable=True, comment="Cumulative output tokens burned by LLM calls"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    indicator_results: Mapped[list["IndicatorResult"]] = relationship(  # noqa: F821
        back_populates="run", cascade="all, delete-orphan"
    )
    discovered_documents: Mapped[list["DiscoveredDocument"]] = relationship(  # noqa: F821
        back_populates="run", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<AnalysisRun id={self.id} country={self.country} status={self.status}>"
