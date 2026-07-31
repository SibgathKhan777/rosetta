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
- **Transcription**: faster-whisper (CPU)
- **On-screen text**: dense interval frame sampling → EAST text-region detector
  (filters to frames actually containing text) → RapidOCR (ONNX Runtime —
  ~6-15x faster than the original EasyOCR on CPU for dense text) →
  low-confidence frames escalated to a vision-LLM (Groq) second pass
- **Explanation**: an LLM call turns the finished transcript + OCR text into a
  teaching-style summary
- **Containerization**: Docker + docker-compose — live in production on a
  free-tier AWS EC2 instance + Vercel; see [DEPLOYMENT.md](./DEPLOYMENT.md)
  for the full zero-cost deployment steps

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
This first pass does **not** attempt to solve that generally (no proxy rotation, no cookie/session
pooling, no retry/backoff strategy beyond what `yt-dlp` does natively) — flagged as a known
limitation to revisit if/when download failure rates become a problem, rather than something to
over-engineer up front.

**Confirmed directly in production**: YouTube specifically blocks requests from the AWS
deployment's IP outright (`Sign in to confirm you're not a bot`, identical across every video
tried and every internal yt-dlp "player client") — this is a known pattern for cloud/datacenter IP
ranges (AWS/GCP/Azure) generally, not a bug in this app. Instagram works fine from the same
deployment. Workaround shipped for this: `POST /jobs/ingest` + `scripts/ingest_video.py` (see
[DEPLOYMENT.md](./DEPLOYMENT.md)) — download the video on a machine that isn't IP-blocked and hand
the file directly to the deployed pipeline, skipping yt-dlp on the server.

## Build stages

This project was built incrementally, each stage confirmed against a real test video before
moving to the next. All stages are complete and verified end-to-end against real videos,
including a 45-minute long-form test.

1. docker-compose skeleton + FastAPI auth — **done**
2. `POST /jobs` + download-only worker (yt-dlp, no processing) — **done**
3. Transcription (single chunk, faster-whisper) — **done**
4. OCR (single frame batch) — **done**
5. Job splitting + parallel chunk/frame fan-out — **done**
6. Vision-LLM escalation, capped per job — **done**, live-verified against Groq
7. Progress reporting + Next.js polling UI — **done**
8. Usage credits tracking (billing/Stripe integration is a later phase, not covered here) — **done**
9. LLM explanation/teaching summary from transcript + OCR — **done**
10. Frame selection rework: scene-cut detection replaced with dense interval sampling +
    EAST text-region pre-filter (scene-change was the wrong signal for "does this frame have
    text" — gradual scrolling/typing never trips a scene-change threshold) — **done**
11. OCR engine swap: EasyOCR → RapidOCR (ONNX Runtime), ~6-15x faster on CPU for dense
    text frames, same or better accuracy — **done** (PaddleOCR was also tried and rejected:
    measured slower than EasyOCR on this workload despite general benchmarks suggesting
    otherwise)
12. Production deployment hardening: rate limiting on auth/job endpoints, hardened
    production docker-compose + Caddy (automatic HTTPS), deployment runbook — **done**
13. Live production deployment: free-tier AWS EC2 (ARM, `t4g.small`) running the full
    backend, Vercel frontend, free HTTPS via a nip.io magic domain — **done**, verified
    with a real signup + real video processed end-to-end through the actual live UI
    (this is also how a mixed-content HTTPS/HTTP bug — browsers silently blocking an
    HTTPS page from calling a plain-HTTP API — got caught; curl alone would have missed it)
14. `POST /jobs/ingest` + `scripts/ingest_video.py`: works around YouTube blocking
    AWS/GCP/Azure datacenter IP ranges outright (confirmed directly — every YouTube
    video and every yt-dlp "player client" failed identically from the AWS IP, while
    Instagram worked fine) — download locally, hand the file straight to the deployed
    pipeline, skipping yt-dlp on the server — **done**, verified end-to-end in production

## Frontend local development

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000, or set PORT to avoid a local conflict
```

Set `NEXT_PUBLIC_API_URL` in `frontend/.env.local` if the API isn't at `http://localhost:8001`.
