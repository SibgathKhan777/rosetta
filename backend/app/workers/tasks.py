import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone

import yt_dlp
from rq.job import Dependency

from app.core.config import settings
from app.database import SessionLocal
from app.models.job import Job, JobResult, JobStatus
from app.queue.redis_conn import default_queue
from app.services.job_state import (
    clear_job_state,
    get_total,
    increment_done,
    load_chunk_result,
    set_total,
    store_chunk_result,
)
from app.services.media import extract_scene_frames, split_audio
from app.services.ocr import ocr_frame
from app.services.progress import upsert_progress
from app.services.transcription import transcribe_audio
from app.storage.s3 import delete_prefix, download_file, upload_file


def download_job(job_id: str) -> None:
    """Fetch metadata + video via yt-dlp and store the raw media in
    S3/MinIO, then hand off to split_job for chunking and fan-out.
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
                # H.264 explicitly preferred: YouTube increasingly serves AV1
                # for mp4, and software AV1 decode (no hardware acceleration
                # in this container) is drastically slower than H.264 —
                # confirmed directly: an AV1 1080p source produced zero
                # decoded frames after 6+ minutes of ffmpeg scene detection.
                "format": (
                    "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]"
                    "/best[ext=mp4]/best"
                ),
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                # Long videos over a real network hit transient read timeouts;
                # retry rather than failing the whole job on one bad socket read.
                "socket_timeout": 30,
                "retries": 10,
                "fragment_retries": 10,
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

            upsert_progress(db, job.id, "download", 100.0)

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

            default_queue.enqueue(split_job, job_id, job_timeout="15m")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    finally:
        db.close()


def split_job(job_id: str) -> None:
    """Chunk audio into fixed-length segments and pick scene-detected frame
    candidates, then fan both out as parallel sub-tasks. A stitch task is
    enqueued depending on every chunk/batch task so it only runs once all of
    them finish (success or failure).
    """
    db = SessionLocal()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        result = db.get(JobResult, uuid.UUID(job_id)) if job else None
        if job is None or result is None or not result.job_metadata:
            return

        upsert_progress(db, job.id, "split", 0.0)

        tmp_dir = tempfile.mkdtemp(prefix=f"split-{job_id}-")
        try:
            source_key = result.job_metadata["source_media_key"]
            ext = os.path.splitext(source_key)[1]
            source_path = os.path.join(tmp_dir, f"source{ext}")
            download_file(source_key, source_path)

            audio_dir = os.path.join(tmp_dir, "audio")
            frames_dir = os.path.join(tmp_dir, "frames")
            os.makedirs(audio_dir, exist_ok=True)
            os.makedirs(frames_dir, exist_ok=True)

            audio_chunks = split_audio(source_path, audio_dir, settings.audio_chunk_seconds)
            scene_frames = extract_scene_frames(source_path, frames_dir, settings.scene_change_threshold)

            upsert_progress(db, job.id, "split", 50.0)

            audio_chunk_keys = []
            for idx, (offset, local_path) in enumerate(audio_chunks):
                key = f"jobs/{job_id}/chunks/audio_{idx:03d}.wav"
                upload_file(local_path, key)
                audio_chunk_keys.append((offset, key))

            frame_keys = []
            for idx, (timestamp, local_path) in enumerate(scene_frames):
                key = f"jobs/{job_id}/frames/frame_{idx:06d}.png"
                upload_file(local_path, key)
                frame_keys.append((timestamp, key))

            batch_size = settings.ocr_batch_size
            frame_batches = [frame_keys[i : i + batch_size] for i in range(0, len(frame_keys), batch_size)]

            total_chunks = len(audio_chunk_keys)
            total_batches = len(frame_batches)

            clear_job_state(job_id, "transcript", total_chunks)
            clear_job_state(job_id, "ocr", total_batches)
            set_total(job_id, "transcript", total_chunks)
            set_total(job_id, "ocr", total_batches)

            upsert_progress(db, job.id, "split", 100.0)
            upsert_progress(db, job.id, "transcription", 0.0)
            upsert_progress(db, job.id, "ocr", 0.0)

            dependency_jobs = []
            for idx, (offset, key) in enumerate(audio_chunk_keys):
                j = default_queue.enqueue(
                    transcribe_chunk_job, job_id, idx, key, offset, job_timeout="15m"
                )
                dependency_jobs.append(j)
            for idx, batch in enumerate(frame_batches):
                j = default_queue.enqueue(ocr_batch_job, job_id, idx, batch, job_timeout="15m")
                dependency_jobs.append(j)

            if dependency_jobs:
                default_queue.enqueue(
                    stitch_job,
                    job_id,
                    depends_on=Dependency(jobs=dependency_jobs, allow_failure=True),
                    job_timeout="10m",
                )
            else:
                # No chunks/frames at all (shouldn't happen for a real video) —
                # stitch immediately so the job doesn't hang forever.
                default_queue.enqueue(stitch_job, job_id, job_timeout="10m")
        except Exception as exc:
            job.status = JobStatus.FAILED.value
            job.error_message = f"Splitting failed: {exc}"[:2000]
            db.commit()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    finally:
        db.close()


def transcribe_chunk_job(job_id: str, chunk_index: int, audio_key: str, offset_seconds: float) -> None:
    tmp_dir = tempfile.mkdtemp(prefix=f"chunk-{job_id}-{chunk_index}-")
    try:
        local_path = os.path.join(tmp_dir, "chunk.wav")
        try:
            download_file(audio_key, local_path)
            transcript, segments = transcribe_audio(local_path)
            for seg in segments:
                seg["start"] += offset_seconds
                seg["end"] += offset_seconds
            store_chunk_result(job_id, "transcript", chunk_index, {"transcript": transcript, "segments": segments})
        except Exception as exc:
            store_chunk_result(job_id, "transcript", chunk_index, {"error": str(exc)[:1000]})
            raise
        finally:
            total = get_total(job_id, "transcript")
            done = increment_done(job_id, "transcript")
            db = SessionLocal()
            try:
                job = db.get(Job, uuid.UUID(job_id))
                if job is not None and total:
                    upsert_progress(db, job.id, "transcription", min(100.0, done / total * 100.0))
            finally:
                db.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def ocr_batch_job(job_id: str, batch_index: int, frame_entries: list) -> None:
    tmp_dir = tempfile.mkdtemp(prefix=f"batch-{job_id}-{batch_index}-")
    try:
        try:
            events = []
            for timestamp, frame_key in frame_entries:
                local_path = os.path.join(tmp_dir, os.path.basename(frame_key))
                download_file(frame_key, local_path)
                for detection in ocr_frame(local_path):
                    detection["timestamp"] = timestamp
                    events.append(detection)
            store_chunk_result(job_id, "ocr", batch_index, {"events": events})
        except Exception as exc:
            store_chunk_result(job_id, "ocr", batch_index, {"error": str(exc)[:1000]})
            raise
        finally:
            total = get_total(job_id, "ocr")
            done = increment_done(job_id, "ocr")
            db = SessionLocal()
            try:
                job = db.get(Job, uuid.UUID(job_id))
                if job is not None and total:
                    upsert_progress(db, job.id, "ocr", min(100.0, done / total * 100.0))
            finally:
                db.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def stitch_job(job_id: str) -> None:
    """Recombine per-chunk transcripts by timestamp offset into one
    continuous transcript, merge OCR batches into a timestamped list, store
    the final result, then purge the job's temporary media — video, audio
    chunks, and frames are not kept once processing is done.
    """
    db = SessionLocal()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None:
            return

        job.status = JobStatus.STITCHING.value
        db.commit()
        upsert_progress(db, job.id, "stitching", 0.0)

        total_chunks = get_total(job_id, "transcript")
        total_batches = get_total(job_id, "ocr")

        transcript_segments = []
        failed_chunks = 0
        for i in range(total_chunks):
            chunk = load_chunk_result(job_id, "transcript", i)
            if chunk is None or "error" in chunk:
                failed_chunks += 1
                continue
            transcript_segments.extend(chunk["segments"])
        transcript_segments.sort(key=lambda s: s["start"])
        transcript = " ".join(seg["text"] for seg in transcript_segments).strip()

        ocr_events = []
        for i in range(total_batches):
            batch = load_chunk_result(job_id, "ocr", i)
            if batch is None or "error" in batch:
                continue
            ocr_events.extend(batch["events"])
        ocr_events.sort(key=lambda e: e["timestamp"])

        result = db.get(JobResult, job.id)
        if result is None:
            result = JobResult(job_id=job.id)
            db.add(result)
        result.transcript = transcript
        result.transcript_segments = transcript_segments
        result.ocr_events = ocr_events

        if total_chunks > 0 and failed_chunks == total_chunks:
            job.status = JobStatus.FAILED.value
            job.error_message = "All audio chunks failed to transcribe"
        else:
            job.status = JobStatus.DONE.value
            if failed_chunks:
                job.error_message = f"{failed_chunks}/{total_chunks} audio chunks failed; transcript is partial"
            job.completed_at = datetime.now(timezone.utc)

        db.commit()
        upsert_progress(db, job.id, "stitching", 100.0)

        clear_job_state(job_id, "transcript", total_chunks)
        clear_job_state(job_id, "ocr", total_batches)
        delete_prefix(f"jobs/{job_id}/")
    finally:
        db.close()
