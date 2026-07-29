# Universal Video Content Extraction Platform

Paste any video URL (YouTube, Instagram, TikTok, X/Twitter, etc.) and get back the spoken
transcript, on-screen text (OCR), and metadata (caption, uploader, engagement stats). Works
uniformly for 30s clips and 1hr+ long-form video — short clips just collapse to a single chunk
of the same pipeline.

## Stack

- **Backend**: Python, FastAPI
- **DB**: PostgreSQL (via SQLAlchemy + Alembic)
- **Queue/cache**: Redis + [RQ](https://python-rq.org/)
- **Object storage**: S3-compatible (MinIO for local dev)
- **Frontend**: Next.js + TypeScript + React (added in build stage 7)
- **Containerization**: Docker + docker-compose

### Why RQ over Celery

The brief allowed switching to Celery if materially better. We stayed with RQ: the fan-out/fan-in
shape this pipeline needs (N audio chunks + N frame batches → one stitch step) is fully covered by
RQ's `Dependency` (a job that depends on a list of parent job IDs), so there's no missing primitive
that would justify Celery's extra operational surface (separate beat/flower processes, broker
config surface). RQ is simpler to run and debug for a single-broker, Redis-only setup like this one.

## Local development

```bash
cp .env.example .env   # then edit secrets if needed
docker compose up -d
```

- API: http://localhost:8001 (mapped to 8000 in the container — host 8000 was already taken by
  an unrelated local process during development; adjust the `api` port mapping in
  `docker-compose.yml` if that's not the case for you)
- MinIO console: http://localhost:9001 (user/pass from `.env`)
- Postgres: localhost:5432
- Redis: localhost:6379

Migrations run automatically on container start (`alembic upgrade head`). To generate a new
migration after changing models:

```bash
docker compose run --rm --no-deps api alembic revision --autogenerate -m "message"
```

## Architecture

See [architecture.mermaid](./architecture.mermaid) for the full pipeline diagram (download → split
→ parallel transcribe/OCR → stitch → store → cleanup).

## Known operational risk: platform blocking

`yt-dlp` is the single integration point for "any video link" — there is intentionally no
per-platform scraping logic. Instagram, TikTok, and similar platforms are known to rate-limit or
outright block `yt-dlp` requests at scale (shared IP ranges, missing auth cookies, bot detection).
This first pass does **not** attempt to solve that (no proxy rotation, no cookie/session pooling,
no retry/backoff strategy beyond what `yt-dlp` does natively) — it's flagged here as a known
limitation to revisit if/when download failure rates become a problem in production, rather than
something to over-engineer up front.

## Build stages

This project was built incrementally, each stage confirmed against a real test video before
moving to the next. All 8 stages are complete and verified end-to-end.

1. docker-compose skeleton + FastAPI auth — **done**
2. `POST /jobs` + download-only worker (yt-dlp, no processing) — **done**
3. Transcription (single chunk, faster-whisper) — **done**
4. OCR (EasyOCR, single frame batch) — **done**
5. Job splitting + parallel chunk/frame fan-out (ffmpeg + scene detection) — **done**
6. Vision-LLM escalation, capped per job — **done** (code path verified with escalation
   disabled/no-API-key; a live vision-LLM call was not exercised — no API key was available
   to test with)
7. Progress reporting + Next.js polling UI — **done**
8. Usage credits tracking (billing/Stripe integration is a later phase, not covered here) — **done**

## Frontend local development

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000, or set PORT to avoid a local conflict
```

Set `NEXT_PUBLIC_API_URL` in `frontend/.env.local` if the API isn't at `http://localhost:8001`.
