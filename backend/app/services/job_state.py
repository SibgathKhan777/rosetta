import json

from app.queue.redis_conn import redis_conn

# Chunk/batch sub-task results and counters live in Redis rather than shared
# local disk, since fan-out tasks may run on any worker process/machine —
# they only share the job_id, not a filesystem.
RESULT_TTL_SECONDS = 3600


def _result_key(job_id: str, kind: str, index: int) -> str:
    return f"job:{job_id}:{kind}:{index}"


def _done_count_key(job_id: str, kind: str) -> str:
    return f"job:{job_id}:{kind}:done_count"


def _total_key(job_id: str, kind: str) -> str:
    return f"job:{job_id}:{kind}:total"


def set_total(job_id: str, kind: str, total: int) -> None:
    redis_conn.set(_total_key(job_id, kind), total, ex=RESULT_TTL_SECONDS)


def get_total(job_id: str, kind: str) -> int:
    raw = redis_conn.get(_total_key(job_id, kind))
    return int(raw) if raw is not None else 0


def store_chunk_result(job_id: str, kind: str, index: int, payload: dict) -> None:
    redis_conn.set(_result_key(job_id, kind, index), json.dumps(payload), ex=RESULT_TTL_SECONDS)


def load_chunk_result(job_id: str, kind: str, index: int) -> dict | None:
    raw = redis_conn.get(_result_key(job_id, kind, index))
    return json.loads(raw) if raw else None


def increment_done(job_id: str, kind: str) -> int:
    key = _done_count_key(job_id, kind)
    done = redis_conn.incr(key)
    redis_conn.expire(key, RESULT_TTL_SECONDS)
    return done


def clear_job_state(job_id: str, kind: str, total: int) -> None:
    keys = [_result_key(job_id, kind, i) for i in range(total)]
    keys += [_done_count_key(job_id, kind), _total_key(job_id, kind)]
    if keys:
        redis_conn.delete(*keys)
