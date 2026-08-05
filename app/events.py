"""Real-time event emission for the pipeline — uses its own sync DB engine."""
import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)


def _safe_json_dumps(data: dict) -> str:
    """JSON-serialize with fallback for non-serializable types."""
    try:
        return json.dumps(data, default=_json_fallback)
    except Exception:
        return str(data)


def _json_fallback(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return str(obj)


_sync_engine = None


def _get_engine():
    global _sync_engine
    if _sync_engine is None:
        url = settings.database_url_sync
        _sync_engine = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=4)
    return _sync_engine


def emit_event(
    run_id: str,
    event_type: str,
    message: str,
    agent: str | None = None,
    indicator_id: str | None = None,
    data: dict | None = None,
) -> None:
    """Emit a pipeline event. Thread-safe — uses its own sync DB connection."""
    try:
        from app.models.run_event import RunEvent

        engine = _get_engine()
        with Session(engine) as session:
            event = RunEvent(
                run_id=run_id,
                event_type=event_type,
                agent=agent,
                indicator_id=indicator_id,
                message=message,
                data=_safe_json_dumps(data) if data else None,
                created_at=datetime.now(timezone.utc),
            )
            session.add(event)
            session.commit()
    except Exception as e:
        logger.warning(f"[Events] Failed to emit event: {e}")
