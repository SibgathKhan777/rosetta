from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    cors_allowed_origins: list[str] = ["http://localhost:3000"]

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/video_platform"

    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "video-platform-temp"
    s3_region: str = "us-east-1"

    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    vision_llm_api_key: str = ""
    vision_llm_base_url: str = "https://api.openai.com/v1"
    vision_llm_model: str = "gpt-4o-mini"
    # Raised from 20 alongside the lower scene_change_threshold: more
    # candidate frames now compete for escalation, so the cap moved up too
    # rather than spreading escalation thinner across a bigger pool.
    vision_llm_max_frames_per_job: int = 30

    # Same LLM/credentials as vision escalation, reused for a text-only call
    # that turns the transcript + OCR text into a teaching explanation.
    explanation_max_input_chars: int = 12000
    # Higher than vision_llm's per-frame budget: reasoning through a full
    # transcript + OCR dump burns much more <think> budget than a single
    # frame does. Confirmed directly: 2048 wasn't enough to even reach an
    # answer on a ~15min video's transcript before hitting max_tokens.
    explanation_max_tokens: int = 4096

    # CPU-friendly per the brief; "base" balances speed/accuracy for dev.
    whisper_model_size: str = "base"
    whisper_compute_type: str = "int8"

    audio_chunk_seconds: int = 300  # 5 min, within the spec's 5-10 min range
    ocr_batch_size: int = 20

    # --- Frame selection (stage 5/10) ---
    # Frames are sampled at a fixed interval rather than on scene cuts —
    # scene-change was the wrong signal for "does this frame have text"
    # (gradual scrolling/typing never trips a scene-change threshold).
    # Raised from 2.0: at 2s, a 15min video produced 192 text-frames, and
    # EasyOCR (CPU-only, ~30-35s/frame observed) turned that into ~2hrs of
    # OCR time alone. 5s trades some density for a practical total runtime —
    # still far denser coverage than the old scene-cut baseline (~30-40
    # frames on the same video).
    frame_sample_interval_seconds: float = 5.0
    # EAST text-region detector filters the dense interval samples down to
    # only frames that actually contain readable text, before OCR ever runs.
    east_model_url: str = (
        "https://github.com/oyyd/frozen_east_text_detection.pb/raw/master/frozen_east_text_detection.pb"
    )
    east_model_path: str = "/root/.cache/east/frozen_east_text_detection.pb"
    # Fixed at EAST's standard input size regardless of source resolution.
    # Confirmed directly: running at native ~1280x720 (nearest-32) took ~5.3s
    # per frame on CPU — with ~450 candidates on a 15min video that blew
    # split_job's 15min timeout outright. 320x320 cuts that to ~0.3s/frame.
    east_input_size: int = 320
    text_detection_confidence: float = 0.5
    # Dedup guard: consecutive interval samples of the same static on-screen
    # text would otherwise all pass the text-detector and flood OCR/escalation
    # with near-duplicates. Raised from 3.0 alongside the interval bump above,
    # for the same reason — cut total selected-frame count for practical
    # OCR runtime on CPU.
    min_frame_gap_seconds: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
