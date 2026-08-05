"""
Module 3 — Result Persister
Saves list of indicator result dicts (from Module 2) to the database
as IndicatorResult ORM rows linked to the AnalysisRun.
"""
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.indicator_result import IndicatorResult

logger = logging.getLogger(__name__)


async def persist_results(
    indicator_results: list[dict[str, Any]],
    run_id: str,
    db: AsyncSession,
) -> None:
    """
    Persist all indicator results to the database.

    Args:
        indicator_results: List of result dicts from the analysis orchestrator.
        run_id: The UUID of the current AnalysisRun.
        db: AsyncSession — NOTE: caller must commit after this function returns.
    """
    if not indicator_results:
        logger.warning(f"[Persist] No indicator results to save for run {run_id}.")
        return

    rows_created = 0
    for res in indicator_results:
        try:
            row = IndicatorResult(
                run_id=run_id,
                pillar_id=res.get("pillar_id", 0),
                indicator_id=res.get("indicator_id", ""),
                raw_score=res.get("final_score"),
                act_and_practice=_truncate(res.get("act_and_practice"), 4000),
                coverage=_truncate(res.get("coverage"), 20),
                impact_comments=_truncate(res.get("impact_comments"), 4000),
                timeframe=_truncate(res.get("timeframe"), 500),
                references=_truncate(res.get("references"), 2000),
                note=_truncate(res.get("note"), 2000),
                confidence=res.get("confidence"),
                verbatim_quote=_truncate(res.get("verbatim_quote"), 4000),
                article_citation=_truncate(res.get("article_citation"), 500),
                law_number_ref=_truncate(res.get("law_number_ref"), 500),
                prosecution_score=res.get("prosecution_score"),
                defense_score=res.get("defense_score"),
                arbiter_score=res.get("arbiter_score"),
                not_found=bool(res.get("not_found", False)),
                discovery_tag=res.get("discovery_tag", "NEW"),
                source_pdf_path=res.get("source_pdf_path"),
                location_ref=_truncate(res.get("location_ref"), 100),
                processing_time=res.get("processing_time"),
                mapping_rationale=_truncate(res.get("mapping_rationale"), 300),
            )
            db.add(row)
            rows_created += 1
        except Exception as exc:
            logger.error(
                f"[Persist] Failed to create IndicatorResult for "
                f"{res.get('indicator_id')}: {exc}"
            )

    await db.flush()
    logger.info(f"[Persist] Saved {rows_created} indicator results for run {run_id}.")


def _truncate(value: Any, max_len: int) -> Any:
    """Truncate a string to a maximum length to avoid DB column overflow."""
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len - 3] + "..."
    return value
