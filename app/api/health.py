"""Health check API router — comprehensive system status."""
import asyncio
import concurrent.futures
from datetime import datetime, timezone
from typing import Any, Optional

import redis.asyncio as aioredis
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.config import settings
from app.database import engine

router = APIRouter(tags=["health"])


class DetailedHealthResponse(BaseModel):
    status: str
    version: str
    timestamp: datetime
    services: dict[str, Any]
    llm: dict[str, Any]
    queue: dict[str, Any]


# Shared thread pool for synchronous LLM SDK calls
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)


async def _check_openai_compat(key: str, base_url: str | None, label: str, source: str, timeout: float = 4.0) -> dict:
    info = {"status": "unconfigured", "api_key_set": False, "message": ""}
    if not key or len(key) <= 5:
        info["message"] = f"{label} not set"
        return info
    info["api_key_set"] = True
    try:
        from openai import OpenAI
        def _run():
            kwargs = {"api_key": key}
            if base_url:
                kwargs["base_url"] = base_url
            client = OpenAI(**kwargs)
            models = client.models.list()
            return [m.id for m in models if source in m.id.lower()]
        models = await asyncio.get_running_loop().run_in_executor(_executor, _run)
        info["status"] = "ok"
        info["message"] = f"Connected — {len(models)} model(s) available"
    except asyncio.TimeoutError:
        info["status"] = "error"
        info["message"] = "Connection timed out"
    except Exception as exc:
        info["status"] = "error"
        info["message"] = str(exc)[:80]
    return info


async def check_gemini(timeout: float = 4.0) -> dict:
    info = {"status": "unconfigured", "api_key_set": False, "message": ""}
    if not settings.google_api_key or len(settings.google_api_key) <= 10:
        info["message"] = "GOOGLE_API_KEY not set"
        return info
    info["api_key_set"] = True
    try:
        import google.generativeai as genai
        def _run():
            genai.configure(api_key=settings.google_api_key)
            return [m.name for m in list(genai.list_models()) if "gemini" in m.name.lower()]
        models = await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(_executor, _run),
            timeout=timeout,
        )
        info["status"] = "ok"
        info["available_models"] = models[:5]
        info["message"] = f"{len(models)} model(s) available"
    except asyncio.TimeoutError:
        info["status"] = "error"
        info["message"] = "Connection timed out"
    except Exception as exc:
        info["status"] = "error"
        info["message"] = str(exc)[:80]
    return info


async def check_ollama(timeout: float = 2.0) -> dict:
    info = {"status": "unchecked", "base_url": settings.ollama_base_url, "models": [], "message": ""}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            if resp.status_code == 200:
                names = [m.get("name") for m in resp.json().get("models", [])]
                info["status"] = "ok"
                info["models"] = names
            else:
                info["status"] = f"http_{resp.status_code}"
    except Exception as exc:
        info["status"] = "unreachable"
        info["message"] = str(exc)[:80]
    return info


@router.get(
    "/health",
    response_model=DetailedHealthResponse,
    summary="System health check",
)
async def health_check() -> DetailedHealthResponse:
    """Returns liveness + readiness status of all system components (concurrent, fast)."""

    HEALTH_TIMEOUT = 12.0

    # ── DB ─────────────────────────────────────────────────────────────────────
    async def _check_db():
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return "ok"
        except Exception as e:
            return f"error: {e}"

    # ── Redis ──────────────────────────────────────────────────────────────────
    async def _check_redis():
        try:
            r = aioredis.from_url(settings.redis_url)
            await r.ping()
            depth = await r.llen("celery")
            await r.aclose()
            return "ok", int(depth)
        except Exception as e:
            return "error", 0

    # ── Celery workers (best-effort, may time out) ─────────────────────────────
    async def _check_workers():
        try:
            from app.workers.celery_app import celery_app
            def _ping():
                insp = celery_app.control.inspect(timeout=3.0)
                return list((insp.ping() or {}).keys())
            workers = await asyncio.get_running_loop().run_in_executor(_executor, _ping)
            return len(workers), workers
        except Exception:
            return 0, []

    # ── Launch all checks concurrently ─────────────────────────────────────────
    db_task = asyncio.create_task(_check_db())
    redis_task = asyncio.create_task(_check_redis())
    gemini_task = asyncio.create_task(check_gemini(timeout=4.0))
    openai_task = asyncio.create_task(_check_openai_compat(settings.openai_api_key, None, "OPENAI_API_KEY", "gpt", timeout=4.0))
    grok_task = asyncio.create_task(_check_openai_compat(settings.xai_api_key, "https://api.x.ai/v1", "XAI_API_KEY", "grok", timeout=4.0))
    deepseek_task = asyncio.create_task(_check_openai_compat(settings.deepseek_api_key, "https://api.deepseek.com", "DEEPSEEK_API_KEY", "deepseek", timeout=4.0))
    ollama_task = asyncio.create_task(check_ollama(timeout=2.0))
    workers_task = asyncio.create_task(_check_workers())

    done, pending = await asyncio.wait(
        [db_task, redis_task, gemini_task, openai_task, grok_task, deepseek_task, ollama_task, workers_task],
        timeout=HEALTH_TIMEOUT,
    )

    # ── Collect results ────────────────────────────────────────────────────────
    db_status = db_task.result() if db_task in done else "timeout"
    redis_status = "timeout"
    queue_info = {"celery_queue_depth": 0, "workers_online": 0, "active_tasks": 0, "reserved_tasks": 0, "note": ""}
    if redis_task in done:
        redis_status, q_depth = redis_task.result()
        queue_info["celery_queue_depth"] = q_depth
    if workers_task in done:
        n_workers, names = workers_task.result()
        queue_info["workers_online"] = n_workers
        if n_workers:
            queue_info["worker_names"] = names

    llm_info = {
        "status": "unconfigured", "message": "",
        "gemini": gemini_task.result() if gemini_task in done else {"status": "timeout", "api_key_set": bool(settings.google_api_key and len(settings.google_api_key) > 10)},
        "openai": openai_task.result() if openai_task in done else {"status": "timeout", "api_key_set": bool(settings.openai_api_key and len(settings.openai_api_key) > 5)},
        "grok": grok_task.result() if grok_task in done else {"status": "timeout", "api_key_set": bool(settings.xai_api_key and len(settings.xai_api_key) > 5)},
        "deepseek": deepseek_task.result() if deepseek_task in done else {"status": "timeout", "api_key_set": bool(settings.deepseek_api_key and len(settings.deepseek_api_key) > 5)},
        "minimax": {"status": "unconfigured", "api_key_set": False},
        "nvidia": {"status": "unconfigured", "api_key_set": False},
        "ollama": ollama_task.result() if ollama_task in done else {"status": "timeout", "base_url": settings.ollama_base_url, "models": []},
        "active": settings.llm_provider or "auto",
    }

    # TokenRouter-derived providers
    if settings.tokenrouter_api_key and len(settings.tokenrouter_api_key) > 5:
        llm_info["minimax"] = {"status": "ok", "api_key_set": True, "model": settings.minimax_model, "message": f"Model: {settings.minimax_model} (free via TokenRouter)"}
        llm_info["nvidia"] = {"status": "ok", "api_key_set": True, "model": settings.nvidia_model, "message": f"Model: {settings.nvidia_model} (free via TokenRouter)"}
    else:
        llm_info["minimax"]["message"] = "TOKENROUTER_API_KEY not set"
        llm_info["nvidia"]["message"] = "TOKENROUTER_API_KEY not set"

    # ── Cancel pending ─────────────────────────────────────────────────────────
    for t in pending:
        try: t.cancel()
        except: pass

    # ── Overall status ────────────────────────────────────────────────────────
    ok_count = sum(1 for p in ["gemini", "openai", "grok", "deepseek", "minimax", "nvidia", "ollama"]
                   if llm_info.get(p, {}).get("status") == "ok")
    llm_info["status"] = "ok" if ok_count > 0 else "unconfigured"
    overall = "ok" if db_status == "ok" and redis_status == "ok" else "degraded"
    if ok_count == 0:
        overall = "degraded"

    return DetailedHealthResponse(
        status=overall,
        version=settings.app_version,
        timestamp=datetime.now(timezone.utc),
        services={"database": db_status, "redis": redis_status},
        llm=llm_info,
        queue=queue_info,
    )
