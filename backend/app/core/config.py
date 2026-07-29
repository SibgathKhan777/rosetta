from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

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
    vision_llm_max_frames_per_job: int = 20

    # CPU-friendly per the brief; "base" balances speed/accuracy for dev.
    whisper_model_size: str = "base"
    whisper_compute_type: str = "int8"

    audio_chunk_seconds: int = 300  # 5 min, within the spec's 5-10 min range
    scene_change_threshold: float = 0.3
    ocr_batch_size: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
