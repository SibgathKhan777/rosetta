import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, HttpUrl


class JobCreateRequest(BaseModel):
    url: HttpUrl


class JobCreateResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    platform: str


class JobProgressResponse(BaseModel):
    stage: str
    percent_complete: float

    model_config = {"from_attributes": True}


class JobResultResponse(BaseModel):
    transcript: str | None = None
    transcript_segments: list[Any] | None = None
    ocr_events: list[Any] | None = None
    metadata: dict[str, Any] | None = None
    explanation: str | None = None

    model_config = {"from_attributes": True}


class JobPartResponse(BaseModel):
    part_index: int
    start_seconds: float
    end_seconds: float
    status: str
    error_message: str | None = None
    transcript: str | None = None
    transcript_segments: list[Any] | None = None
    ocr_events: list[Any] | None = None
    explanation: str | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class JobStatusResponse(BaseModel):
    job_id: uuid.UUID
    url: str
    platform: str | None
    status: str
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    progress: list[JobProgressResponse]
    result: JobResultResponse | None = None
    parts: list[JobPartResponse] | None = None

    model_config = {"from_attributes": True}


class JobListItem(BaseModel):
    job_id: uuid.UUID
    url: str
    platform: str | None
    status: str
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}
