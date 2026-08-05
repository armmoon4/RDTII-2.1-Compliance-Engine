"""Analysis API router — submit, poll, export, list, delete runs."""
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.analysis_run import AnalysisRun, RunStatus
from app.models.discovered_document import DiscoveredDocument
from app.models.indicator_result import IndicatorResult
from app.models.run_event import RunEvent
from app.schemas.analysis import (
    AllResultsItemSchema,
    AnalysisRequest,
    AnalysisRunSchema,
    AnalysisRunSummarySchema,
    AnalysisSubmitResponse,
    AuditResponseSchema,
    ReviewQueueItemSchema,
    RunEventListResponse,
    RunEventSchema,
    TokenUsageSchema,
)
from app.modules.output.exporters import _results_to_records
from app.workers.tasks import run_full_pipeline

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/run", response_model=AnalysisSubmitResponse, status_code=202)
async def submit_analysis(
    request: AnalysisRequest,
    db: AsyncSession = Depends(get_db),
) -> AnalysisSubmitResponse:
    """Submit a new RDTII analysis job. Returns a run_id to poll for results."""
    import uuid

    run_id = str(uuid.uuid4())
    pillar_str = (
        ",".join(map(str, request.pillar_ids)) if request.pillar_ids else None
    )

    run = AnalysisRun(
        id=run_id,
        country=request.country,
        status=RunStatus.QUEUED,
        pillar_ids_requested=pillar_str,
        pdf_url=request.pdf_url,
        llm_provider=request.llm_provider,
    )
    db.add(run)
    await db.commit()

    # Dispatch Celery task
    task = run_full_pipeline.delay(
        run_id=run_id,
        country=request.country,
        pillar_ids=request.pillar_ids,
        indicator_ids=request.indicator_ids,
        pdf_url=request.pdf_url,
    )

    # Save Celery task ID
    run.celery_task_id = task.id
    await db.commit()

    return AnalysisSubmitResponse(
        run_id=run_id,
        status=RunStatus.QUEUED,
        message=f"Analysis job queued for {request.country}. Poll /analysis/{run_id} for status.",
    )


@router.get("/indicators")
async def list_indicators() -> list[dict]:
    """List all 61 RDTII indicators with IDs, titles, and pillar mappings."""
    from app.modules.discovery.query_generator import INDICATOR_QUESTION_BANK
    return [
        {
            "id": meta.indicator_id,
            "title": meta.title,
            "pillar_id": int(meta.indicator_id.split(".")[0]),
            "research_question": meta.research_question,
        }
        for meta in INDICATOR_QUESTION_BANK.values()
    ]


@router.get("/countries")
async def list_countries(
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """List all countries that have been analysed (distinct)."""
    result = await db.execute(
        select(AnalysisRun.country).distinct().order_by(AnalysisRun.country)
    )
    countries = [row[0] for row in result.all()]
    return countries


@router.get("/results/all", response_model=list[AllResultsItemSchema])
async def get_all_results(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> list[AllResultsItemSchema]:
    """Get all indicator results across all runs, newest first."""
    result = await db.execute(
        select(IndicatorResult)
        .order_by(IndicatorResult.id.desc())
        .limit(limit)
        .offset(offset)
        .options(selectinload(IndicatorResult.run))
    )
    items = result.scalars().all()
    records = []
    for ir in items:
        records.append({
            "id": ir.id,
            "run_id": ir.run_id,
            "country": ir.run.country if ir.run else "Unknown",
            "pillar_id": ir.pillar_id,
            "indicator_id": ir.indicator_id,
            "raw_score": ir.raw_score,
            "act_and_practice": ir.act_and_practice or "—",
            "coverage": ir.coverage or "N/A",
            "impact_comments": ir.impact_comments or "—",
            "timeframe": ir.timeframe or "—",
            "references": ir.references or "—",
            "note": ir.note or "—",
            "confidence": ir.confidence,
            "verbatim_quote": ir.verbatim_quote or "",
            "article_citation": ir.article_citation or "",
            "discovery_tag": ir.discovery_tag or "NEW",
            "location_ref": ir.location_ref or "",
            "mapping_rationale": ir.mapping_rationale or "",
            "created_at": ir.created_at.isoformat() if ir.created_at else "",
        })
    return records


@router.get("/results/{country}")
async def get_results_by_country(
    country: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Get all indicator results for the most recent completed run of a country."""
    result = await db.execute(
        select(AnalysisRun)
        .where(
            AnalysisRun.country == country,
            AnalysisRun.status == RunStatus.COMPLETE,
        )
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
        .options(selectinload(AnalysisRun.indicator_results))
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(
            status_code=404,
            detail=f"No completed analysis found for {country}.",
        )
    return _results_to_records(run.indicator_results)


@router.get("/results/{country}/{indicator}")
async def get_indicator_result(
    country: str,
    indicator: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single indicator result for the most recent completed run."""
    result = await db.execute(
        select(AnalysisRun)
        .where(
            AnalysisRun.country == country,
            AnalysisRun.status == RunStatus.COMPLETE,
        )
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(
            status_code=404,
            detail=f"No completed analysis found for {country}.",
        )
    ir_result = await db.execute(
        select(IndicatorResult).where(
            IndicatorResult.run_id == run.id,
            IndicatorResult.indicator_id == indicator,
        )
    )
    ir = ir_result.scalar_one_or_none()
    if not ir:
        raise HTTPException(
            status_code=404,
            detail=f"Indicator {indicator} not found for {country}.",
        )
    records = _results_to_records([ir])
    return records[0] if records else {}


@router.get("/runs", response_model=list[AnalysisRunSummarySchema])
async def list_runs(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AnalysisRunSummarySchema]:
    """List all analysis runs (newest first)."""
    result = await db.execute(
        select(AnalysisRun)
        .order_by(AnalysisRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    runs = result.scalars().all()

    summaries = []
    for run in runs:
        summaries.append(
            AnalysisRunSummarySchema(
                id=run.id,
                country=run.country,
                status=run.status,
                created_at=run.created_at,
                completed_at=run.completed_at,
                total_indicators=run.total_indicators,
                completed_indicators=run.completed_indicators,
                error_message=run.error_message,
                current_activity=run.current_activity,
                llm_provider=run.llm_provider,
            )
        )
    return summaries


@router.get("/token-usage", response_model=list[TokenUsageSchema])
async def list_token_usage(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[TokenUsageSchema]:
    """List token usage for all runs (newest first)."""
    result = await db.execute(
        select(AnalysisRun)
        .order_by(AnalysisRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    runs = result.scalars().all()
    return [_run_to_token_usage(r) for r in runs]


@router.get("/{run_id}/token-usage", response_model=TokenUsageSchema)
async def get_run_token_usage(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> TokenUsageSchema:
    """Get token usage for a specific run."""
    result = await db.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
    return _run_to_token_usage(run)


def _run_to_token_usage(run: AnalysisRun) -> TokenUsageSchema:
    inp = run.total_input_tokens or 0
    out = run.total_output_tokens or 0
    cost = _estimate_token_cost(run.llm_provider or "auto", inp, out)
    return TokenUsageSchema(
        run_id=run.id,
        country=run.country,
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        llm_provider=run.llm_provider,
        total_input_tokens=inp,
        total_output_tokens=out,
        total_tokens=inp + out,
        estimated_cost_usd=round(cost, 6),
        indicators_analysed=run.completed_indicators,
    )


_PROVIDER_COST_PER_1K = {
    "openai": (0.00015, 0.00060),
    "gemini": (0.00015, 0.00060),
    "deepseek": (0.00027, 0.00110),
    "grok": (0.00200, 0.01000),
    "minimax": (0, 0),
    "nvidia": (0, 0),
    "ollama": (0, 0),
}


def _estimate_token_cost(provider: str, input_tokens: int, output_tokens: int) -> float:
    p = provider.lower()
    cost_per_1k = _PROVIDER_COST_PER_1K.get(p)
    if not cost_per_1k:
        cost_per_1k = (0.00015, 0.00060)
    in_cost = (input_tokens / 1000) * cost_per_1k[0]
    out_cost = (output_tokens / 1000) * cost_per_1k[1]
    return in_cost + out_cost


@router.get("/{run_id}", response_model=AnalysisRunSchema)
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)) -> AnalysisRunSchema:
    """Get full analysis results for a run including all indicator results."""
    result = await db.execute(
        select(AnalysisRun)
        .where(AnalysisRun.id == run_id)
        .options(
            selectinload(AnalysisRun.indicator_results),
            selectinload(AnalysisRun.discovered_documents),
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
    return AnalysisRunSchema.model_validate(run)


@router.get("/{run_id}/export")
async def export_results(
    run_id: str,
    format: str = Query(
        default="json",
        pattern="^(json|csv|rdtii_flat_csv|submission_csv|excel)$",
    ),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Export results for a completed run.

    format options:
      - json           : Full JSON with audit fields
      - csv            : Official RDTII template CSV — 13 columns with pillar header
                         rows and split reference URL columns (matches the Excel template)
      - rdtii_flat_csv : Legacy 9-column flat RDTII CSV (§2.1)
      - submission_csv : Hackathon submission spec columns (§17)
      - excel          : Excel workbook with three sheets:
                           • RDTII_Template (primary, matches official template)
                           • RDTII_9col (legacy flat)
                           • Submission (hackathon spec)
    """
    result = await db.execute(
        select(AnalysisRun)
        .where(AnalysisRun.id == run_id)
        .options(selectinload(AnalysisRun.indicator_results))
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
    if run.status != RunStatus.COMPLETE:
        raise HTTPException(status_code=409, detail="Run not yet complete.")

    from app.modules.output.exporters import export_csv, export_excel, export_json

    country_slug = run.country.replace(" ", "_") if run.country else "country"

    if format == "json":
        data = export_json(run.indicator_results)
        return StreamingResponse(
            io.BytesIO(data.encode()),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=RDTII_{country_slug}_results.json"},
        )
    elif format == "csv":
        # Primary export — matches official RDTII Excel template
        buf = export_csv(run.indicator_results, format="rdtii")
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=RDTII_{country_slug}_template.csv"},
        )
    elif format == "rdtii_flat_csv":
        # Legacy 9-column flat export
        buf = export_csv(run.indicator_results, format="rdtii_flat")
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=RDTII_{country_slug}_9col.csv"},
        )
    elif format == "submission_csv":
        buf = export_csv(run.indicator_results, format="submission", country=run.country)
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=RDTII_{country_slug}_submission.csv"},
        )
    elif format == "excel":
        buf = export_excel(run.indicator_results, run.country)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=RDTII_{country_slug}_results.xlsx"},
        )


@router.get("/{run_id}/events", response_model=RunEventListResponse)
async def get_run_events(
    run_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> RunEventListResponse:
    """Get real-time events for a run (newest first, paginated)."""
    result = await db.execute(
        select(RunEvent)
        .where(RunEvent.run_id == run_id)
        .order_by(RunEvent.id.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    rows = result.scalars().all()
    has_more = len(rows) > limit
    events = [RunEventSchema.model_validate(r) for r in rows[:limit]]
    next_offset = offset + limit
    return RunEventListResponse(events=events, next_offset=next_offset, has_more=has_more)


@router.get("/{run_id}/stream")
async def stream_run_events(run_id: str):
    """SSE endpoint — streams new events in real-time as they happen."""
    import asyncio
    import json as _json
    from app.database import AsyncSessionLocal

    async def event_generator():
        last_id = 0
        while True:
            session = AsyncSessionLocal()
            try:
                result = await session.execute(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.id > last_id)
                    .order_by(RunEvent.id.asc())
                )
                rows = result.scalars().all()
                for event in rows:
                    last_id = event.id
                    data = {
                        "id": event.id,
                        "event_type": event.event_type,
                        "agent": event.agent,
                        "indicator_id": event.indicator_id,
                        "message": event.message,
                        "data": event.data,
                        "created_at": event.created_at.isoformat(),
                    }
                    yield f"event: {event.event_type}\ndata: {_json.dumps(data)}\n\n"
            finally:
                await session.close()
            if not rows:
                yield "event: heartbeat\ndata: {}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/audit/{result_id}", response_model=AuditResponseSchema)
async def get_audit_view(
    result_id: int, db: AsyncSession = Depends(get_db)
) -> AuditResponseSchema:
    """Side-by-side audit view for a single indicator result.
    
    Returns the AI extraction (verbatim quote, citation, score) alongside
    source document metadata for human verification.
    """
    result = await db.execute(
        select(IndicatorResult)
        .where(IndicatorResult.id == result_id)
        .options(selectinload(IndicatorResult.run))
    )
    ir = result.scalar_one_or_none()
    if not ir:
        raise HTTPException(status_code=404, detail=f"IndicatorResult {result_id} not found.")

    docs = await db.execute(
        select(DiscoveredDocument)
        .where(
            and_(
                DiscoveredDocument.run_id == ir.run_id,
                DiscoveredDocument.indicator_id == ir.indicator_id,
                DiscoveredDocument.zone1_passed == True,
            )
        )
        .limit(10)
    )
    source_docs = [
        {
            "url": d.url,
            "source_type": d.source_type.value if hasattr(d.source_type, 'value') else str(d.source_type),
            "language": d.language,
            "ocr_quality_cer": d.ocr_quality_cer,
            "download_status": d.download_status,
        }
        for d in docs.scalars().all()
    ]

    country = ir.run.country if ir.run else "Unknown"
    return AuditResponseSchema(
        result_id=ir.id,
        run_id=ir.run_id,
        country=country,
        indicator_id=ir.indicator_id,
        pillar_id=ir.pillar_id,
        raw_score=ir.raw_score,
        act_and_practice=ir.act_and_practice,
        impact_comments=ir.impact_comments,
        verbatim_quote=ir.verbatim_quote,
        article_citation=ir.article_citation,
        references=ir.references,
        confidence=ir.confidence,
        not_found=ir.not_found,
        discovery_tag=ir.discovery_tag or "NEW",
        source_documents=source_docs,
    )


@router.get("/review/queue", response_model=list[ReviewQueueItemSchema])
async def get_review_queue(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ReviewQueueItemSchema]:
    """Human-review queue — indicators flagged by the Arbiter.
    
    Returns results where:
    - confidence < 0.7 (low confidence threshold)
    - prosecution and defense scores disagree (delta >= 0.15)
    - not_found but with prosecution evidence found
    """
    threshold = 0.7

    result = await db.execute(
        select(IndicatorResult)
        .where(
            (IndicatorResult.confidence < float(threshold)) |
            (
                (IndicatorResult.prosecution_score.isnot(None)) &
                (IndicatorResult.defense_score.isnot(None)) &
                (IndicatorResult.prosecution_score - IndicatorResult.defense_score >= 0.15)
            ) |
            (
                (IndicatorResult.not_found == True) &
                (IndicatorResult.prosecution_score > 0.0)
            )
        )
        .order_by(IndicatorResult.confidence.asc())
        .limit(limit)
        .options(selectinload(IndicatorResult.run))
    )
    items = result.scalars().all()

    queue = []
    for ir in items:
        country = ir.run.country if ir.run else "Unknown"
        queue.append(
            ReviewQueueItemSchema(
                result_id=ir.id,
                run_id=ir.run_id,
                country=country,
                indicator_id=ir.indicator_id,
                pillar_id=ir.pillar_id,
                raw_score=ir.raw_score,
                confidence=ir.confidence,
                not_found=ir.not_found,
                discovery_tag=ir.discovery_tag or "NEW",
                prosecution_score=ir.prosecution_score,
                defense_score=ir.defense_score,
                verbatim_quote=ir.verbatim_quote,
                article_citation=ir.article_citation,
                impact_comments=ir.impact_comments,
                reason="Confidence below threshold" if (ir.confidence is not None and ir.confidence < threshold)
                       else "Arbiter flagged for review",
            )
        )
    return queue


@router.get("/export/all")
async def export_all_results(
    format: str = Query(
        default="csv",
        pattern="^(json|csv|rdtii_flat_csv|submission_csv|excel)$",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Export all indicator results across all runs."""
    result = await db.execute(
        select(IndicatorResult)
        .order_by(IndicatorResult.pillar_id, IndicatorResult.indicator_id, IndicatorResult.id)
        .options(selectinload(IndicatorResult.run))
    )
    items = result.scalars().all()

    from app.modules.output.exporters import (
        _results_to_records,
        _results_to_rdtii_template_rows,
        _results_to_submission_records,
    )
    import pandas as pd

    if format == "json":
        records = _results_to_records(items)
        data = json.dumps(records, indent=2, default=str)
        return StreamingResponse(
            io.BytesIO(data.encode()),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=RDTII_all_results.json"},
        )

    elif format == "csv":
        rows = _results_to_rdtii_template_rows(items)
        output_cols = [
            "Pillar_ID", "Indicator_ID", "Raw Score", "Act and/or practice",
            "Coverage", "Impact or comments on Acts or practices", "Timeframe",
            "References", "References_2", "References_3", "References_4", "References_5", "Note",
        ]
        clean_rows = [{k: v for k, v in row.items() if k != "_is_pillar_header"} for row in rows]
        df = pd.DataFrame(clean_rows, columns=output_cols)
        buf = io.BytesIO()
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=RDTII_all_results_template.csv"},
        )

    elif format == "rdtii_flat_csv":
        records = _results_to_records(items)
        cols = [
            "pillar_id", "indicator_id", "raw_score", "act_and_practice",
            "coverage", "impact_comments", "timeframe", "references", "note",
        ]
        labels = {
            "pillar_id": "Pillar_ID", "indicator_id": "Indicator_ID",
            "raw_score": "Raw Score", "act_and_practice": "Act and/or practice",
            "coverage": "Coverage", "impact_comments": "Impact or comments on Acts or practices",
            "timeframe": "Timeframe", "references": "References", "note": "Note",
        }
        df = pd.DataFrame(records, columns=cols)
        df.rename(columns=labels, inplace=True)
        buf = io.BytesIO()
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=RDTII_all_results_9col.csv"},
        )

    elif format == "submission_csv":
        from collections import defaultdict
        by_country = defaultdict(list)
        for ir in items:
            country = ir.run.country if ir.run else "Unknown"
            by_country[country].append(ir)
        all_records = []
        for country, country_items in sorted(by_country.items()):
            all_records.extend(_results_to_submission_records(country_items, country))
        sub_cols = [
            "economy", "law_name", "law_number_ref", "last_amended",
            "indicator_id", "article_section", "discovery_tag", "location_ref",
            "verbatim_snippet", "mapping_rationale", "source_url", "confidence", "notes",
        ]
        sub_labels = {
            "economy": "Economy", "law_name": "Law Name", "law_number_ref": "Law Number / Ref",
            "last_amended": "Last Amended", "indicator_id": "Indicator ID",
            "article_section": "Article / Section", "discovery_tag": "Discovery Tag",
            "location_ref": "Location Reference", "verbatim_snippet": "Verbatim Snippet",
            "mapping_rationale": "Mapping Rationale", "source_url": "Source URL",
            "confidence": "Confidence", "notes": "Notes",
        }
        df = pd.DataFrame(all_records, columns=sub_cols)
        df.rename(columns=sub_labels, inplace=True)
        buf = io.BytesIO()
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=RDTII_all_results_submission.csv"},
        )

    elif format == "excel":
        from collections import defaultdict
        from app.modules.output.exporters import export_excel
        by_country = defaultdict(list)
        for ir in items:
            country = ir.run.country if ir.run else "Unknown"
            by_country[country].append(ir)
        merged_items = []
        for country, country_items in sorted(by_country.items()):
            merged_items.extend(country_items)
        buf = export_excel(merged_items, "All Countries")
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=RDTII_all_results.xlsx"},
        )


@router.delete("/{run_id}", status_code=204)
async def delete_run(run_id: str, db: AsyncSession = Depends(get_db)) -> None:
    """Delete an analysis run and all its related data."""
    result = await db.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
    await db.delete(run)
    await db.commit()
