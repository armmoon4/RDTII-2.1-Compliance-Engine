"""Celery tasks — the full 3-module pipeline runs here asynchronously."""
import asyncio
import logging
from datetime import datetime, timezone

from celery import Task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.events import emit_event
from app.models.analysis_run import AnalysisRun, RunStatus
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Lazy singleton: async engine created on first task use so that
# Celery ForkPool children each get their own engine in their own event loop.
_worker_engine = None
_WorkerSessionLocal = None


def _get_worker_session() -> AsyncSession:
    global _worker_engine, _WorkerSessionLocal
    if _WorkerSessionLocal is None:
        _worker_engine = create_async_engine(
            settings.database_url,
            echo=settings.app_debug,
            poolclass=NullPool,
        )
        _WorkerSessionLocal = async_sessionmaker(
            bind=_worker_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _WorkerSessionLocal()


def _run_async(coro):
    """Helper to run async code inside a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, name="run_full_pipeline", max_retries=1)
def run_full_pipeline(
    self: Task,
    run_id: str,
    country: str,
    pillar_ids: list | None = None,
    indicator_ids: list | None = None,
    pdf_url: str | None = None,
) -> dict:
    """
    Full 3-module RDTII analysis pipeline.

    Module 1: Document Discovery
    Module 2: Multi-Agent Adversarial Analysis
    Module 3: Persist results
    """
    logger.info(f"[Task {self.request.id}] Starting pipeline for {country} run={run_id}")
    return _run_async(_pipeline(self, run_id, country, pillar_ids, indicator_ids, pdf_url))


async def _pipeline(task, run_id, country, pillar_ids, indicator_ids, pdf_url):
    async with _get_worker_session() as db:
        # Fetch run
        result = await db.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            logger.error(f"Run {run_id} not found in DB.")
            return {"error": "run not found"}

        # Determine indicator IDs: explicit list, or derive from pillar filter
        from app.modules.analysis.scoring_engine import VALID_SCORES, get_indicator_ids_for_pillars
        if indicator_ids:
            all_indicators = list(VALID_SCORES.keys())
            invalid = [i for i in indicator_ids if i not in all_indicators]
            if invalid:
                raise ValueError(f"Invalid indicator IDs: {invalid}")
            indicator_ids_to_use = indicator_ids
        else:
            indicator_ids_to_use = get_indicator_ids_for_pillars(pillar_ids)

        try:
            # Lazy imports inside try block so import errors are caught and marked FAILED
            from app.modules.discovery.discovery_orchestrator import run_discovery
            from app.modules.analysis.analysis_orchestrator import run_analysis
            from app.modules.analysis.agents.ai_client import set_provider
            from app.modules.output.result_persister import persist_results

            # Apply the LLM provider selected at submission time
            if run.llm_provider:
                set_provider(run.llm_provider)
                logger.info(f"[{run_id}] LLM provider set to: {run.llm_provider}")

            # Initialize token tracking for this run
            from app.modules.analysis.agents.ai_client import set_run_id as _set_run_id
            _set_run_id(run_id)
            # ── Module 1: Document Discovery ─────────────────────────────────
            run.status = RunStatus.DISCOVERING
            run.total_indicators = len(indicator_ids_to_use)
            run.current_activity = "Searching the web for related legislation and regulations..."
            await db.commit()
            emit_event(run_id, "STATUS", f"Discovery started for {country} ({len(indicator_ids_to_use)} indicators)",
                       data={"country": country, "indicator_count": len(indicator_ids_to_use)})
            logger.info(f"[{run_id}] Module 1: Discovery starting...")

            discovered_docs = await run_discovery(
                country=country,
                indicator_ids=indicator_ids_to_use,
                run_id=run_id,
                pdf_url=pdf_url,
                db=db,
            )
            emit_event(run_id, "STATUS", f"Discovery complete: {len(discovered_docs)} documents passed Zone 1",
                       data={"doc_count": len(discovered_docs)})
            logger.info(f"[{run_id}] Module 1: {len(discovered_docs)} documents discovered.")

            # ── Module 2: Analysis ────────────────────────────────────────────
            run.status = RunStatus.ANALYSING
            run.current_activity = "Initializing LLM agents and chunking documents..."
            await db.commit()
            emit_event(run_id, "STATUS", f"Analysis started — running 3-agent pipeline on {len(indicator_ids_to_use)} indicators",
                       data={"indicator_count": len(indicator_ids_to_use)})
            logger.info(f"[{run_id}] Module 2: Analysis starting...")

            indicator_results = await run_analysis(
                discovered_docs=discovered_docs,
                country=country,
                indicator_ids=indicator_ids_to_use,
                run_id=run_id,
                db=db,
                run=run,
                has_provided_pdf=bool(pdf_url),
            )
            logger.info(f"[{run_id}] Module 2: {len(indicator_results)} indicators analysed.")

            # ── Module 3: Persist ─────────────────────────────────────────────
            await persist_results(indicator_results, run_id, db)

            # Capture token usage
            from app.modules.analysis.agents.ai_client import get_run_tokens as _get_tokens, clear_run_tokens as _clear_tokens
            tokens = _get_tokens()
            run.total_input_tokens = tokens["input"]
            run.total_output_tokens = tokens["output"]
            _clear_tokens()

            run.status = RunStatus.COMPLETE
            run.completed_at = datetime.now(timezone.utc)
            await db.commit()
            emit_event(run_id, "STATUS", f"Pipeline complete — {len(indicator_results)} indicators scored, "
                       f"tokens burned: {tokens['input'] + tokens['output']:,}",
                       data={"indicator_count": len(indicator_results), **tokens})
            logger.info(f"[{run_id}] Pipeline COMPLETE. Tokens: {tokens}")
            return {"run_id": run_id, "status": "COMPLETE", "indicators": len(indicator_results), **tokens}

        except Exception as exc:
            logger.exception(f"[{run_id}] Pipeline FAILED: {exc}")
            emit_event(run_id, "STATUS", f"Pipeline failed: {exc}", data={"error": str(exc)})
            # Still capture any partial token usage before the crash
            from app.modules.analysis.agents.ai_client import get_run_tokens as _get_tokens, clear_run_tokens as _clear_tokens
            tokens = _get_tokens()
            if tokens["input"] or tokens["output"]:
                run.total_input_tokens = tokens["input"]
                run.total_output_tokens = tokens["output"]
            _clear_tokens()
            run.status = RunStatus.FAILED
            run.error_message = str(exc)
            await db.commit()
            raise
