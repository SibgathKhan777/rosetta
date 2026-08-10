import os
import shutil
import tempfile
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.limiter import limiter
from app.database import get_db
from app.models.job import Job, JobResult, JobStatus
from app.models.usage_credits import UsageCredits
from app.models.user import User
from app.queue.redis_conn import default_queue
from app.schemas.job import (
    JobCreateRequest,
    JobCreateResponse,
    JobListItem,
    JobPartResponse,
    JobProgressResponse,
    JobResultResponse,
    JobStatusResponse,
)
from app.services.credits import MIN_CREDITS_TO_SUBMIT, deduct_credits, estimate_cost
from app.services.platform import detect_platform
from app.services.progress import upsert_progress
from app.storage.s3 import upload_file
from app.workers.tasks import download_job, split_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _to_result_response(result: JobResult | None) -> JobResultResponse | None:
    if result is None:
        return None
    return JobResultResponse(
        transcript=result.transcript,
        transcript_segments=result.transcript_segments,
        ocr_events=result.ocr_events,
        metadata=result.job_metadata,
        explanation=result.explanation,
    )


def _to_parts_response(job: Job) -> list[JobPartResponse] | None:
    if not job.parts:
        return None
    return [
        JobPartResponse(
            part_index=p.part_index,
            start_seconds=p.start_seconds,
            end_seconds=p.end_seconds,
            status=p.status,
            error_message=p.error_message,
            transcript=p.transcript,
            transcript_segments=p.transcript_segments,
            ocr_events=p.ocr_events,
            explanation=p.explanation,
            completed_at=p.completed_at,
        )
        for p in job.parts
    ]


def _get_owned_job(db: Session, job_id: uuid.UUID, user: User) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("", response_model=JobCreateResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
def create_job(
    request: Request,
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


@router.post("/ingest", response_model=JobCreateResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
def ingest_job(
    request: Request,
    url: str = Form(...),
    title: str = Form(""),
    caption: str = Form(""),
    uploader: str = Form(""),
    view_count: int = Form(0),
    like_count: int = Form(0),
    comment_count: int = Form(0),
    duration_seconds: float = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Accepts a video already downloaded elsewhere plus its metadata, and
    feeds it directly into the pipeline from split_job onward — skipping
    yt-dlp/download_job entirely. Exists because some platforms (YouTube)
    block requests from cloud/datacenter IP ranges outright; the video can
    instead be downloaded on a machine that isn't blocked (see
    scripts/ingest_video.py) and handed to this endpoint.
    """
    cost = estimate_cost(duration_seconds)
    credits = db.get(UsageCredits, user.id)
    if credits is None or credits.credits_remaining < cost:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient credits")

    platform = detect_platform(url)
    job = Job(
        user_id=user.id,
        url=url,
        platform=platform,
        status=JobStatus.PROCESSING.value,
        duration_seconds=duration_seconds,
    )
    db.add(job)
    db.flush()

    ext = os.path.splitext(file.filename or "")[1] or ".mp4"
    tmp_dir = tempfile.mkdtemp(prefix=f"ingest-{job.id}-")
    try:
        local_path = os.path.join(tmp_dir, f"source{ext}")
        with open(local_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        s3_key = f"jobs/{job.id}/source{ext}"
        upload_file(local_path, s3_key)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    metadata = {
        "title": title,
        "caption": caption,
        "uploader": uploader,
        "view_count": view_count,
        "like_count": like_count,
        "comment_count": comment_count,
        "duration_seconds": duration_seconds,
        "source_media_key": s3_key,
    }
    result = JobResult(job_id=job.id, job_metadata=metadata)
    db.add(result)
    upsert_progress(db, job.id, "split", 0.0)
    db.commit()

    deduct_credits(db, user.id, cost)

    default_queue.enqueue(split_job, str(job.id), job_timeout="20m")

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


def build_job_status_response(job: Job) -> JobStatusResponse:
    """Shared builder — also used by the WebSocket endpoint (app/api/ws.py)
    so both the REST and push paths return byte-identical shapes. Field
    names don't line up 1:1 with the ORM model (job_id vs id, progress vs
    progress_entries, nested result/parts transforms), so this can't be
    replaced with a plain model_validate(job).
    """
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
        parts=_to_parts_response(job),
    )


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = _get_owned_job(db, job_id, user)
    return build_job_status_response(job)


@router.get("/{job_id}/result", response_model=JobResultResponse)
def get_job_result(job_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = _get_owned_job(db, job_id, user)
    if job.result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not available yet")
    return _to_result_response(job.result)
