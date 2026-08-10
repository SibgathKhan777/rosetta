import asyncio
import uuid

from fastapi import APIRouter, WebSocket
from redis.asyncio import Redis as AsyncRedis

from app.api.jobs import build_job_status_response
from app.core.config import settings
from app.core.security import decode_access_token
from app.database import SessionLocal
from app.models.job import Job

router = APIRouter(prefix="/ws", tags=["ws"])

# Separate async client for WebSocket subscribers only — does not replace
# app/queue/redis_conn.py's sync client, which RQ and job_state.py keep
# using unchanged.
_async_redis: AsyncRedis | None = None


def _get_async_redis() -> AsyncRedis:
    global _async_redis
    if _async_redis is None:
        _async_redis = AsyncRedis.from_url(settings.redis_url)
    return _async_redis


def _fetch_job_status(job_id: uuid.UUID, user_id: uuid.UUID) -> dict | None:
    """Sync DB read; always called via asyncio.to_thread so it never blocks
    the event loop that's also serving other WS connections on this process.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None or job.user_id != user_id:
            return None
        return build_job_status_response(job).model_dump(mode="json")
    finally:
        db.close()


@router.websocket("/jobs/{job_id}")
async def job_events_ws(websocket: WebSocket, job_id: uuid.UUID, token: str = ""):
    user_id = decode_access_token(token)
    if user_id is None:
        await websocket.close(code=1008)  # valid pre-accept per ASGI spec
        return

    initial = await asyncio.to_thread(_fetch_job_status, job_id, uuid.UUID(user_id))
    if initial is None:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    await websocket.send_json(initial)

    channel = f"job:{job_id}:events"
    pubsub = _get_async_redis().pubsub()
    await pubsub.subscribe(channel)
    try:
        forward = asyncio.create_task(_forward(websocket, pubsub, job_id, uuid.UUID(user_id)))
        recv = asyncio.create_task(websocket.receive_text())  # detects client disconnect
        done, pending = await asyncio.wait({forward, recv}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in done:
            t.exception()  # drain to avoid "exception never retrieved" warnings
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()


async def _forward(websocket: WebSocket, pubsub, job_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        # Payload is a lightweight change signal, not full state — refetch
        # the same JobStatusResponse shape GET /jobs/{id} returns, so the
        # frontend reuses its existing setJob(data) handler unchanged.
        data = await asyncio.to_thread(_fetch_job_status, job_id, user_id)
        if data is not None:
            await websocket.send_json(data)
