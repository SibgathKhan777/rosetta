import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone

import yt_dlp

from app.database import SessionLocal
from app.models.job import Job, JobResult, JobStatus
from app.services.media import extract_audio, extract_frames
from app.services.ocr import ocr_frame
from app.services.progress import upsert_progress
from app.services.transcription import transcribe_audio
from app.storage.s3 import upload_file


def download_job(job_id: str) -> None:
    """Fetch metadata + video via yt-dlp, store the raw media in S3/MinIO,
    transcribe the full audio as a single chunk, then OCR a fixed-interval
    frame batch (stage 4 — scene-detected frame selection + splitting come
    in stage 5).
    """
    db = SessionLocal()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None:
            return

        job.status = JobStatus.DOWNLOADING.value
        db.commit()
        upsert_progress(db, job.id, "download", 0.0)

        tmp_dir = tempfile.mkdtemp(prefix=f"job-{job_id}-")
        try:
            outtmpl = os.path.join(tmp_dir, "source.%(ext)s")
            ydl_opts = {
                "outtmpl": outtmpl,
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(job.url, download=True)
            except Exception as exc:
                job.status = JobStatus.FAILED.value
                job.error_message = str(exc)[:2000]
                db.commit()
                return

            upsert_progress(db, job.id, "download", 60.0)

            candidates = [f for f in os.listdir(tmp_dir) if f.startswith("source.")]
            if not candidates:
                job.status = JobStatus.FAILED.value
                job.error_message = "yt-dlp reported success but produced no output file"
                db.commit()
                return
            downloaded_path = os.path.join(tmp_dir, candidates[0])

            s3_key = f"jobs/{job_id}/source{os.path.splitext(downloaded_path)[1]}"
            upload_file(downloaded_path, s3_key)

            upsert_progress(db, job.id, "download", 90.0)

            duration = info.get("duration") or 0
            metadata = {
                "title": info.get("title"),
                "caption": info.get("description"),
                "uploader": info.get("uploader"),
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "comment_count": info.get("comment_count"),
                "duration_seconds": duration,
                "source_media_key": s3_key,
            }

            result = db.get(JobResult, job.id)
            if result is None:
                result = JobResult(job_id=job.id)
                db.add(result)
            result.job_metadata = metadata

            job.duration_seconds = duration
            job.status = JobStatus.PROCESSING.value
            db.commit()

            upsert_progress(db, job.id, "download", 100.0)
            upsert_progress(db, job.id, "transcription", 0.0)

            audio_path = os.path.join(tmp_dir, "audio.wav")
            try:
                extract_audio(downloaded_path, audio_path)
                transcript, segments = transcribe_audio(audio_path)
            except Exception as exc:
                job.status = JobStatus.FAILED.value
                job.error_message = f"Transcription failed: {exc}"[:2000]
                db.commit()
                return

            result.transcript = transcript
            result.transcript_segments = segments
            db.commit()

            upsert_progress(db, job.id, "transcription", 100.0)
            upsert_progress(db, job.id, "ocr", 0.0)

            frames_dir = os.path.join(tmp_dir, "frames")
            os.makedirs(frames_dir, exist_ok=True)
            try:
                frames = extract_frames(downloaded_path, frames_dir, interval_seconds=2.0)
                ocr_events = []
                for timestamp, frame_path in frames:
                    for detection in ocr_frame(frame_path):
                        detection["timestamp"] = timestamp
                        ocr_events.append(detection)
            except Exception as exc:
                job.status = JobStatus.FAILED.value
                job.error_message = f"OCR failed: {exc}"[:2000]
                db.commit()
                return

            result.ocr_events = ocr_events

            job.status = JobStatus.DONE.value
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

            upsert_progress(db, job.id, "ocr", 100.0)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    finally:
        db.close()
