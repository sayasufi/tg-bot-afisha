from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    api_port: int = Field(default=8000, alias="API_PORT")
    database_url: str = Field(
        default="postgresql+psycopg://afisha:afisha@postgres:5432/afisha",
        alias="DATABASE_URL",
    )
    sync_database_url: str = Field(
        default="postgresql+psycopg://afisha:afisha@postgres:5432/afisha",
        alias="SYNC_DATABASE_URL",
    )
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    celery_broker_url: str = Field(default="redis://redis:6379/1", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://redis:6379/2", alias="CELERY_RESULT_BACKEND")

    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")

    llm_api_base_url: str = Field(default="http://176.109.82.96:5000", alias="LLM_API_BASE_URL")
    llm_timeout_seconds: float = Field(default=20.0, alias="LLM_TIMEOUT_SECONDS")

    yandex_geocoder_key: str = Field(default="", alias="YANDEX_GEOCODER_KEY")
    nominatim_base_url: str = Field(default="https://nominatim.openstreetmap.org", alias="NOMINATIM_BASE_URL")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_webapp_url: str = Field(default="http://localhost:5173", alias="TELEGRAM_WEBAPP_URL")
    # Comma-separated CORS allowlist. Empty → derived from telegram_webapp_url +
    # known prod hosts + localhost dev (see apps/api/app/main.py).
    cors_origins: str = Field(default="", alias="CORS_ORIGINS")

    telethon_api_id: int | None = Field(default=None, alias="TELETHON_API_ID")
    telethon_api_hash: str = Field(default="", alias="TELETHON_API_HASH")
    telethon_session: str = Field(default="afisha_session", alias="TELETHON_SESSION")

    kudago_base_url: str = "https://kudago.com/public-api/v1.4"
    yandex_afisha_base_url: str = "https://afisha.yandex.ru/api/graphql"
    afisha_ru_base_url: str = "https://www.afisha.ru"
    # afisha.ru blocks datacenter/cloud IP ranges (e.g. GCP) — every request 429s.
    # Set a residential proxy URL (http://user:pass@host:port) to enable afisha
    # ingestion; empty keeps it OFF (the fetch tasks no-op).
    afisha_proxy: str = Field(default="", alias="AFISHA_PROXY")

    default_city: str = Field(default="Moscow", alias="DEFAULT_CITY")
    default_country: str = Field(default="RU", alias="DEFAULT_COUNTRY")

    # MinIO (S3-compatible) object storage for cached event images.
    minio_endpoint: str = Field(default="http://minio:9000", alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="okrest", alias="MINIO_ROOT_USER")
    minio_secret_key: str = Field(default="okrest-minio-secret", alias="MINIO_ROOT_PASSWORD")
    minio_bucket: str = Field(default="event-media", alias="MINIO_BUCKET")
    # Absolute base the client uses to load images (e.g. https://host/v1/media).
    # Falls back to the same-origin API path when empty.
    media_public_base: str = Field(default="", alias="MEDIA_PUBLIC_BASE")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
