"""SQLAlchemy ORM model — IndicatorResult stores the 9-column RDTII output."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class IndicatorResult(Base):
    __tablename__ = "indicator_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )

    # ── 9-Column RDTII Schema ─────────────────────────────────────────────────
    pillar_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    indicator_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    raw_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    act_and_practice: Mapped[str | None] = mapped_column(Text, nullable=True)
    coverage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    impact_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeframe: Mapped[str | None] = mapped_column(Text, nullable=True)
    references: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Agent metadata ────────────────────────────────────────────────────────
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    verbatim_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    article_citation: Mapped[str | None] = mapped_column(Text, nullable=True)
    law_number_ref: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Official reference number of the law (e.g. 'No. 119, 1988', 'Regulation (EU) 2016/679')"
    )
    prosecution_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    defense_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    arbiter_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    not_found: Mapped[bool] = mapped_column(default=False, nullable=False)

    # ── Audit trail per submission spec §17 — ──
    discovery_tag: Mapped[str | None] = mapped_column(
        String(10), nullable=True, default="NEW",
        comment='"NEW" = independent find; "KNOWN" = sample kit'
    )
    source_pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_ref: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="PDF page or HTML anchor for the cited provision"
    )
    processing_time: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Seconds to process this indicator"
    )
    mapping_rationale: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Why this maps to this indicator (max 300 chars)"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationship
    run: Mapped["AnalysisRun"] = relationship(back_populates="indicator_results")  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<IndicatorResult indicator={self.indicator_id} "
            f"score={self.raw_score} run={self.run_id}>"
        )
