import uuid

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.job import JobProgress


def upsert_progress(db: Session, job_id: uuid.UUID, stage: str, percent_complete: float) -> None:
    stmt = insert(JobProgress).values(job_id=job_id, stage=stage, percent_complete=percent_complete)
    stmt = stmt.on_conflict_do_update(
        index_elements=["job_id", "stage"],
        set_={"percent_complete": percent_complete, "updated_at": func.now()},
    )
    db.execute(stmt)
    db.commit()
