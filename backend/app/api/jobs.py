import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models.job import Job, JobResult, JobStatus
from app.models.usage_credits import UsageCredits
from app.models.user import User
from app.queue.redis_conn import default_queue
from app.schemas.job import (
    JobCreateRequest,
    JobCreateResponse,
    JobListItem,
    JobProgressResponse,
    JobResultResponse,
    JobStatusResponse,
)
from app.services.credits import MIN_CREDITS_TO_SUBMIT
from app.services.platform import detect_platform
from app.services.progress import upsert_progress
from app.workers.tasks import download_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _to_result_response(result: JobResult | None) -> JobResultResponse | None:
    if result is None:
        return None
    return JobResultResponse(
        transcript=result.transcript,
        transcript_segments=result.transcript_segments,
        ocr_events=result.ocr_events,
        metadata=result.job_metadata,
    )


def _get_owned_job(db: Session, job_id: uuid.UUID, user: User) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("", response_model=JobCreateResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    credits = db.get(UsageCredits, user.id)
    if credits is None or credits.credits_remaining < MIN_CREDITS_TO_SUBMIT:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient credits")

    url = str(payload.url)
    platform = detect_platform(url)

    job = Job(user_id=user.id, url=url, platform=platform, status=JobStatus.QUEUED.value)
    db.add(job)
    db.commit()
    db.refresh(job)

    upsert_progress(db, job.id, "download", 0.0)

    default_queue.enqueue(download_job, str(job.id), job_timeout="30m")

    return JobCreateResponse(job_id=job.id, status=job.status, platform=platform)


@router.get("", response_model=list[JobListItem])
def list_jobs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    jobs = db.query(Job).filter(Job.user_id == user.id).order_by(Job.created_at.desc()).all()
    return [
        JobListItem(
            job_id=j.id,
            url=j.url,
            platform=j.platform,
            status=j.status,
            created_at=j.created_at,
            completed_at=j.completed_at,
        )
        for j in jobs
    ]


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = _get_owned_job(db, job_id, user)
    return JobStatusResponse(
        job_id=job.id,
        url=job.url,
        platform=job.platform,
        status=job.status,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
        progress=[
            JobProgressResponse(stage=p.stage, percent_complete=p.percent_complete) for p in job.progress_entries
        ],
        result=_to_result_response(job.result),
    )


@router.get("/{job_id}/result", response_model=JobResultResponse)
def get_job_result(job_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = _get_owned_job(db, job_id, user)
    if job.result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not available yet")
    return _to_result_response(job.result)
