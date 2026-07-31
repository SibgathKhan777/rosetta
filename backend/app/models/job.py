import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    STITCHING = "stitching"
    DONE = "done"
    FAILED = "failed"


class JobPartStatus(str, enum.Enum):
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED.value, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="jobs")
    progress_entries = relationship("JobProgress", back_populates="job", cascade="all, delete-orphan")
    result = relationship("JobResult", back_populates="job", uselist=False, cascade="all, delete-orphan")
    parts = relationship(
        "JobPart", back_populates="job", cascade="all, delete-orphan", order_by="JobPart.part_index"
    )


class JobProgress(Base):
    __tablename__ = "job_progress"
    __table_args__ = (UniqueConstraint("job_id", "stage", name="uq_job_progress_job_stage"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    percent_complete: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    job = relationship("Job", back_populates="progress_entries")


class JobResult(Base):
    __tablename__ = "job_results"

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), primary_key=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_segments: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    ocr_events: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    job_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    job = relationship("Job", back_populates="result")


class JobPart(Base):
    """One independent result for a fixed-length slice of a long (>1hr)
    video — own transcript/OCR/explanation, own status, delivered to the
    user as soon as that slice finishes rather than waiting for the whole
    video. Videos at or under the long-video threshold never get rows here;
    their single combined result lives on JobResult instead.
    """

    __tablename__ = "job_parts"
    __table_args__ = (UniqueConstraint("job_id", "part_index", name="uq_job_parts_job_part_index"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, index=True)
    part_index: Mapped[int] = mapped_column(nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=JobPartStatus.PROCESSING.value, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # This part's own slice of the whole-video chunk/frame keys, computed
    # once up front by _fanout_long_video and consumed later by _start_part —
    # parts are started one at a time (not all fanned out immediately) so an
    # earlier part's stitch isn't stuck queued behind every other part's raw
    # work on a single-worker deployment (see stage 18 follow-up fix).
    audio_chunk_keys: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    frame_keys: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_segments: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    ocr_events: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job = relationship("Job", back_populates="parts")
