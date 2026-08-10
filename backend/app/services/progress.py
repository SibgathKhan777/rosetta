import json
import logging
import uuid

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.job import JobProgress
from app.queue.redis_conn import redis_conn

logger = logging.getLogger(__name__)


def publish_job_event(job_id: uuid.UUID, payload: dict) -> None:
    """Best-effort PUBLISH to this job's channel so the FastAPI WebSocket
    endpoint (a separate process from the RQ worker that calls this) can
    push the update instantly instead of the browser polling for it. Never
    raises — a missed publish just means the frontend's polling fallback
    (or the next real event) picks up the state on its next tick; this must
    never be allowed to fail a job that otherwise succeeded.
    """
    try:
        redis_conn.publish(f"job:{job_id}:events", json.dumps({"job_id": str(job_id), **payload}))
    except Exception:
        logger.warning("Failed to publish job event", exc_info=True)


def upsert_progress(db: Session, job_id: uuid.UUID, stage: str, percent_complete: float) -> None:
    stmt = insert(JobProgress).values(job_id=job_id, stage=stage, percent_complete=percent_complete)
    stmt = stmt.on_conflict_do_update(
        index_elements=["job_id", "stage"],
        set_={"percent_complete": percent_complete, "updated_at": func.now()},
    )
    db.execute(stmt)
    db.commit()
    publish_job_event(job_id, {"type": "progress", "stage": stage, "percent_complete": percent_complete})
