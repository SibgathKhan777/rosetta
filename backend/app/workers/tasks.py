import math
import os
import shutil
import tempfile
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import yt_dlp
from rq.job import Dependency

from app.core.config import settings
from app.database import SessionLocal
from app.models.job import Job, JobPart, JobPartStatus, JobResult, JobStatus
from app.queue.redis_conn import default_queue
from app.services.credits import deduct_credits, estimate_cost
from app.services.explanation import generate_explanation
from app.services.job_state import (
    clear_job_state,
    decrement_remaining,
    get_total,
    increment_done,
    load_chunk_result,
    set_remaining,
    set_total,
    store_chunk_result,
)
from app.services.media import extract_interval_frames, split_audio
from app.services.ocr import ocr_frame
from app.services.progress import upsert_progress
from app.services.text_detector import has_text
from app.services.transcription import transcribe_audio
from app.services.vision_llm import escalate_frame
from app.services.vision_llm import is_enabled as is_vision_llm_enabled
from app.storage.s3 import delete_prefix, download_file, upload_file


def _select_text_frames(candidates: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """Filter densely-sampled candidate frames down to ones that actually
    contain text (via EAST), deduping consecutive text frames that are too
    close together in time — otherwise a long static on-screen text block
    would pass every interval sample and flood OCR with near-duplicates.
    """
    selected = []
    last_kept_ts = None
    for timestamp, path in candidates:
        if not has_text(path):
            continue
        if last_kept_ts is not None and (timestamp - last_kept_ts) < settings.min_frame_gap_seconds:
            continue
        selected.append((timestamp, path))
        last_kept_ts = timestamp
    return selected


def _frame_badness(frame_summary: dict) -> float:
    confidence = frame_summary["min_confidence"]
    return 1.0 if confidence is None else 1.0 - confidence


def _escalate_worst_frames(job_id: str, frame_summaries: list[dict]) -> list[dict]:
    """Second-pass vision-LLM read on the top-N worst frames per job (capped
    by settings.vision_llm_max_frames_per_job) — never every low-confidence
    frame uncapped, to keep cost bounded on long videos.
    """
    worst = sorted(frame_summaries, key=_frame_badness, reverse=True)[: settings.vision_llm_max_frames_per_job]

    tmp_dir = tempfile.mkdtemp(prefix=f"vision-{job_id}-")
    escalated = []
    try:
        for fs in worst:
            local_path = os.path.join(tmp_dir, os.path.basename(fs["frame_key"]))
            try:
                download_file(fs["frame_key"], local_path)
                text = escalate_frame(local_path)
            except Exception:
                continue  # best-effort — a failed escalation never fails the job
            if text:
                escalated.append({
                    "text": text,
                    "confidence": None,
                    "frame": os.path.basename(fs["frame_key"]),
                    "timestamp": fs["timestamp"],
                    "source": "vision_llm",
                })
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return escalated


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

            # Actual cost is only knowable now that yt-dlp reported the real
            # duration — the submission-time check was just a nonzero-balance
            # gate (see app/services/credits.py).
            deduct_credits(db, job.user_id, estimate_cost(duration))

            default_queue.enqueue(split_job, job_id, job_timeout="20m")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    finally:
        db.close()


def split_job(job_id: str) -> None:
    """Chunk audio into fixed-length segments and pick text-bearing frame
    candidates, then hand off to one of two fan-out strategies: videos at or
    under long_video_threshold_seconds get today's single whole-video
    stitch (_fanout_short_video); longer videos get cut into independent
    parts, each with its own stitch barrier (_fanout_long_video), so a
    part's result appears as soon as that part finishes rather than waiting
    for the whole video.
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
            candidate_frames = extract_interval_frames(source_path, frames_dir, settings.frame_sample_interval_seconds)
            text_frames = _select_text_frames(candidate_frames)

            upsert_progress(db, job.id, "split", 50.0)

            audio_chunk_keys = []
            for idx, (offset, local_path) in enumerate(audio_chunks):
                key = f"jobs/{job_id}/chunks/audio_{idx:03d}.wav"
                upload_file(local_path, key)
                audio_chunk_keys.append((offset, key))

            frame_keys = []
            for idx, (timestamp, local_path) in enumerate(text_frames):
                key = f"jobs/{job_id}/frames/frame_{idx:06d}.png"
                upload_file(local_path, key)
                frame_keys.append((timestamp, key))

            upsert_progress(db, job.id, "split", 100.0)

            is_long_form = (job.duration_seconds or 0) > settings.long_video_threshold_seconds
            if is_long_form:
                _fanout_long_video(db, job, audio_chunk_keys, frame_keys)
            else:
                _fanout_short_video(db, job, audio_chunk_keys, frame_keys)
        except Exception as exc:
            job.status = JobStatus.FAILED.value
            job.error_message = f"Splitting failed: {exc}"[:2000]
            db.commit()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    finally:
        db.close()


def _fanout_short_video(db, job: Job, audio_chunk_keys: list, frame_keys: list) -> None:
    """Today's whole-video fan-out, unchanged: one flat set of chunk/batch
    tasks, one stitch_job barrier depending on all of them.
    """
    job_id = str(job.id)
    batch_size = settings.ocr_batch_size
    frame_batches = [frame_keys[i : i + batch_size] for i in range(0, len(frame_keys), batch_size)]

    total_chunks = len(audio_chunk_keys)
    total_batches = len(frame_batches)

    clear_job_state(job_id, "transcript", total_chunks)
    clear_job_state(job_id, "ocr", total_batches)
    set_total(job_id, "transcript", total_chunks)
    set_total(job_id, "ocr", total_batches)

    upsert_progress(db, job.id, "transcription", 0.0)
    upsert_progress(db, job.id, "ocr", 0.0)

    dependency_jobs = []
    for idx, (offset, key) in enumerate(audio_chunk_keys):
        j = default_queue.enqueue(
            transcribe_chunk_job, job_id, job_id, idx, key, offset, "transcription", job_timeout="15m"
        )
        dependency_jobs.append(j)
    for idx, batch in enumerate(frame_batches):
        # 15m wasn't enough margin: text-dense frames (the new
        # selection favors these) pushed a 20-frame EasyOCR batch
        # past 900s and got killed mid-batch, losing that batch's
        # OCR results entirely.
        j = default_queue.enqueue(ocr_batch_job, job_id, job_id, idx, batch, "ocr", job_timeout="30m")
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


def _fanout_long_video(db, job: Job, audio_chunk_keys: list, frame_keys: list) -> None:
    """Videos over long_video_threshold_seconds get cut into
    video_part_seconds-long parts, each with its own independent
    transcript/OCR/explanation. Parts are started ONE AT A TIME
    (_start_part), not all fanned out here — RQ appends a dependent job
    (like a part's stitch) to the BACK of the queue once its dependencies
    resolve, so fanning out every part's raw work up front means an early
    part's stitch ends up stuck behind every later part's raw tasks on a
    single-worker deployment, and nothing becomes visible until nearly the
    whole video is done. Chaining part-by-part guarantees part 0's result
    appears before part 1's work even starts, regardless of worker count.
    """
    job_id = str(job.id)
    part_seconds = settings.video_part_seconds
    duration = job.duration_seconds
    num_parts = max(1, math.ceil(duration / part_seconds))

    chunks_by_part: dict[int, list] = defaultdict(list)
    for offset, key in audio_chunk_keys:
        p_idx = min(int(offset // part_seconds), num_parts - 1)
        chunks_by_part[p_idx].append([offset, key])

    frames_by_part: dict[int, list] = defaultdict(list)
    for timestamp, key in frame_keys:
        p_idx = min(int(timestamp // part_seconds), num_parts - 1)
        frames_by_part[p_idx].append([timestamp, key])

    for p in range(num_parts):
        db.add(
            JobPart(
                job_id=job.id,
                part_index=p,
                start_seconds=p * part_seconds,
                end_seconds=min((p + 1) * part_seconds, duration),
                status=JobPartStatus.PROCESSING.value,
                audio_chunk_keys=chunks_by_part.get(p, []),
                frame_keys=frames_by_part.get(p, []),
            )
        )
    db.commit()

    upsert_progress(db, job.id, "parts", 0.0)
    set_remaining(job_id, "parts", num_parts)

    _start_part(job_id, 0)


def _start_part(job_id: str, part_index: int) -> None:
    """Enqueues one part's own chunk/OCR-batch tasks plus its stitch
    barrier. Called directly for part 0 by _fanout_long_video, and then
    chained by stitch_part_job for every subsequent part once the previous
    one finishes — see _fanout_long_video's docstring for why.
    """
    db = SessionLocal()
    try:
        part = db.query(JobPart).filter_by(job_id=uuid.UUID(job_id), part_index=part_index).one_or_none()
        if part is None:
            return

        state_key = f"{job_id}:p{part_index}"
        part_chunks = part.audio_chunk_keys or []
        part_frames = part.frame_keys or []
        batch_size = settings.ocr_batch_size
        part_frame_batches = [part_frames[i : i + batch_size] for i in range(0, len(part_frames), batch_size)]

        clear_job_state(state_key, "transcript", len(part_chunks))
        clear_job_state(state_key, "ocr", len(part_frame_batches))
        set_total(state_key, "transcript", len(part_chunks))
        set_total(state_key, "ocr", len(part_frame_batches))

        dependency_jobs = []
        for local_idx, (offset, key) in enumerate(part_chunks):
            # offset stays video-absolute (not part-relative) so this
            # part's transcript segments keep correct whole-video timestamps.
            j = default_queue.enqueue(
                transcribe_chunk_job, job_id, state_key, local_idx, key, offset, None, job_timeout="15m"
            )
            dependency_jobs.append(j)
        for local_idx, batch in enumerate(part_frame_batches):
            j = default_queue.enqueue(
                ocr_batch_job, job_id, state_key, local_idx, batch, None, job_timeout="30m"
            )
            dependency_jobs.append(j)

        if dependency_jobs:
            default_queue.enqueue(
                stitch_part_job,
                job_id,
                part_index,
                depends_on=Dependency(jobs=dependency_jobs, allow_failure=True),
                job_timeout="10m",
            )
        else:
            # A short trailing part can have zero chunks/batches — mirrors
            # the short-video path's own empty-candidates fallback.
            default_queue.enqueue(stitch_part_job, job_id, part_index, job_timeout="10m")
    finally:
        db.close()


def transcribe_chunk_job(
    job_id: str,
    state_key: str,
    chunk_index: int,
    audio_key: str,
    offset_seconds: float,
    progress_stage: str | None = "transcription",
) -> None:
    tmp_dir = tempfile.mkdtemp(prefix=f"chunk-{job_id}-{chunk_index}-")
    try:
        local_path = os.path.join(tmp_dir, "chunk.wav")
        try:
            download_file(audio_key, local_path)
            transcript, segments = transcribe_audio(local_path)
            for seg in segments:
                seg["start"] += offset_seconds
                seg["end"] += offset_seconds
            store_chunk_result(state_key, "transcript", chunk_index, {"transcript": transcript, "segments": segments})
        except Exception as exc:
            store_chunk_result(state_key, "transcript", chunk_index, {"error": str(exc)[:1000]})
            raise
        finally:
            total = get_total(state_key, "transcript")
            done = increment_done(state_key, "transcript")
            if progress_stage:
                db = SessionLocal()
                try:
                    job = db.get(Job, uuid.UUID(job_id))
                    if job is not None and total:
                        upsert_progress(db, job.id, progress_stage, min(100.0, done / total * 100.0))
                finally:
                    db.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def ocr_batch_job(
    job_id: str,
    state_key: str,
    batch_index: int,
    frame_entries: list,
    progress_stage: str | None = "ocr",
) -> None:
    tmp_dir = tempfile.mkdtemp(prefix=f"batch-{job_id}-{batch_index}-")
    try:
        try:
            events = []
            frame_summaries = []
            for timestamp, frame_key in frame_entries:
                local_path = os.path.join(tmp_dir, os.path.basename(frame_key))
                download_file(frame_key, local_path)
                detections = ocr_frame(local_path)
                for detection in detections:
                    detection["timestamp"] = timestamp
                    events.append(detection)
                confidences = [d["confidence"] for d in detections]
                frame_summaries.append({
                    "frame_key": frame_key,
                    "timestamp": timestamp,
                    # None (empty result) is treated as worse than any
                    # low-confidence detection when ranking escalation candidates.
                    "min_confidence": min(confidences) if confidences else None,
                })
            store_chunk_result(state_key, "ocr", batch_index, {"events": events, "frame_summaries": frame_summaries})
        except Exception as exc:
            store_chunk_result(state_key, "ocr", batch_index, {"error": str(exc)[:1000]})
            raise
        finally:
            total = get_total(state_key, "ocr")
            done = increment_done(state_key, "ocr")
            if progress_stage:
                db = SessionLocal()
                try:
                    job = db.get(Job, uuid.UUID(job_id))
                    if job is not None and total:
                        upsert_progress(db, job.id, progress_stage, min(100.0, done / total * 100.0))
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
        frame_summaries = []
        for i in range(total_batches):
            batch = load_chunk_result(job_id, "ocr", i)
            if batch is None or "error" in batch:
                continue
            ocr_events.extend(batch["events"])
            frame_summaries.extend(batch.get("frame_summaries", []))

        if is_vision_llm_enabled() and frame_summaries:
            ocr_events.extend(_escalate_worst_frames(job_id, frame_summaries))

        ocr_events.sort(key=lambda e: e["timestamp"])

        result = db.get(JobResult, job.id)
        if result is None:
            result = JobResult(job_id=job.id)
            db.add(result)
        result.transcript = transcript
        result.transcript_segments = transcript_segments
        result.ocr_events = ocr_events

        if is_vision_llm_enabled() and (transcript or ocr_events):
            ocr_text = "\n".join(e["text"] for e in ocr_events)
            title = (result.job_metadata or {}).get("title", "")
            result.explanation = generate_explanation(title, transcript, ocr_text)

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


def stitch_part_job(job_id: str, part_index: int) -> None:
    """Same aggregation shape as stitch_job, scoped to one part's own
    chunks/batches — writes onto that JobPart row instead of JobResult, and
    never touches the shared S3 prefix or job.status directly (that's
    _finalize_long_job's job, once every sibling part is terminal).
    """
    db = SessionLocal()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None:
            return
        part = db.query(JobPart).filter_by(job_id=job.id, part_index=part_index).one_or_none()
        if part is None:
            return

        state_key = f"{job_id}:p{part_index}"
        total_chunks = get_total(state_key, "transcript")
        total_batches = get_total(state_key, "ocr")

        transcript_segments = []
        failed_chunks = 0
        for i in range(total_chunks):
            chunk = load_chunk_result(state_key, "transcript", i)
            if chunk is None or "error" in chunk:
                failed_chunks += 1
                continue
            transcript_segments.extend(chunk["segments"])
        transcript_segments.sort(key=lambda s: s["start"])
        transcript = " ".join(seg["text"] for seg in transcript_segments).strip()

        ocr_events = []
        frame_summaries = []
        for i in range(total_batches):
            batch = load_chunk_result(state_key, "ocr", i)
            if batch is None or "error" in batch:
                continue
            ocr_events.extend(batch["events"])
            frame_summaries.extend(batch.get("frame_summaries", []))

        if is_vision_llm_enabled() and frame_summaries:
            ocr_events.extend(_escalate_worst_frames(state_key, frame_summaries))

        ocr_events.sort(key=lambda e: e["timestamp"])

        part.transcript = transcript
        part.transcript_segments = transcript_segments
        part.ocr_events = ocr_events

        if is_vision_llm_enabled() and (transcript or ocr_events):
            ocr_text = "\n".join(e["text"] for e in ocr_events)
            metadata = (job.result.job_metadata if job.result else None) or {}
            base_title = metadata.get("title", "")
            part_title = f"{base_title} — part {part_index + 1}" if base_title else f"Part {part_index + 1}"
            # transcript/ocr_text here are only one part's worth of content
            # (a few minutes), so explanation_max_input_chars essentially
            # never truncates — unlike the whole-video stitch_job path.
            part.explanation = generate_explanation(part_title, transcript, ocr_text)

        if total_chunks > 0 and failed_chunks == total_chunks:
            part.status = JobPartStatus.FAILED.value
            part.error_message = "All audio chunks failed to transcribe for this part"
        else:
            part.status = JobPartStatus.DONE.value
            if failed_chunks:
                part.error_message = f"{failed_chunks}/{total_chunks} audio chunks failed; this part's transcript is partial"
        part.completed_at = datetime.now(timezone.utc)
        db.commit()

        clear_job_state(state_key, "transcript", total_chunks)
        clear_job_state(state_key, "ocr", total_batches)

        num_parts = len(job.parts)
        done_parts = db.query(JobPart).filter(
            JobPart.job_id == job.id, JobPart.status != JobPartStatus.PROCESSING.value
        ).count()
        if num_parts:
            upsert_progress(db, job.id, "parts", min(100.0, done_parts / num_parts * 100.0))
        db.commit()

        remaining = decrement_remaining(job_id, "parts")
        if remaining <= 0:
            _finalize_long_job(db, job)
        else:
            next_index = part_index + 1
            if next_index < num_parts:
                default_queue.enqueue(_start_part, job_id, next_index)
    finally:
        db.close()


def _finalize_long_job(db, job: Job) -> None:
    """Runs once, triggered by whichever stitch_part_job call observes the
    atomic remaining-parts counter hit zero — sets the parent job's overall
    status and does the single shared-S3-prefix cleanup for the whole video.
    """
    parts = db.query(JobPart).filter_by(job_id=job.id).order_by(JobPart.part_index).all()
    failed_parts = [p for p in parts if p.status == JobPartStatus.FAILED.value]

    if parts and len(failed_parts) == len(parts):
        job.status = JobStatus.FAILED.value
        job.error_message = "All parts failed to process"
    else:
        job.status = JobStatus.DONE.value
        if failed_parts:
            failed_labels = ", ".join(str(p.part_index + 1) for p in failed_parts)
            job.error_message = f"Part(s) {failed_labels} failed; other parts completed"
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    delete_prefix(f"jobs/{job.id}/")
