"""SQLAlchemy ORM model — DiscoveredDocument tracks every document found by Module 1."""
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SourceType(str, PyEnum):
    PRIMARY_HIGH = "PRIMARY_HIGH"         # Matches known official portal
    PRIMARY_GAZETTE = "PRIMARY_GAZETTE"   # Gazette / subsidiary legislation
    PRIMARY_MEDIUM = "PRIMARY_MEDIUM"     # .gov domain, not known portal
    SECONDARY_LEAD = "SECONDARY_LEAD"     # News / law firm / Wikipedia — lead only
    SECONDARY_APPROVED = "SECONDARY_APPROVED"  # UNCTAD/WB for approved indicators
    EXCLUDED = "EXCLUDED"                 # Draft, future-dated, or repealed


class EnforcementStatus(str, PyEnum):
    IN_FORCE = "IN_FORCE"
    DRAFT = "DRAFT"
    REPEALED = "REPEALED"
    FUTURE_DATED = "FUTURE_DATED"
    UNKNOWN = "UNKNOWN"


class DiscoveredDocument(Base):
    __tablename__ = "discovered_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )

    # ── Source identification ─────────────────────────────────────────────────
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source_type: Mapped[SourceType] = mapped_column(
        SAEnum(SourceType), default=SourceType.PRIMARY_MEDIUM, nullable=False
    )
    enforcement_status: Mapped[EnforcementStatus] = mapped_column(
        SAEnum(EnforcementStatus), default=EnforcementStatus.UNKNOWN, nullable=False
    )
    zone1_passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── Content ───────────────────────────────────────────────────────────────
    original_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    translated_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    download_status: Mapped[str] = mapped_column(
        String(20), default="PENDING", nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_quality_cer: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)

    # ── Discovery metadata ────────────────────────────────────────────────────
    indicator_id: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    search_query_used: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationship
    run: Mapped["AnalysisRun"] = relationship(back_populates="discovered_documents")  # noqa: F821

    def __repr__(self) -> str:
        return f"<DiscoveredDocument url={self.url[:60]} zone1={self.zone1_passed}>"
