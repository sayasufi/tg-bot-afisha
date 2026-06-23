import sys
from functools import lru_cache

from pydantic import Field, model_validator
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

    # Meilisearch — typo-tolerant typeahead engine. Disabled by default → the API falls back to the
    # Postgres trigram search, so nothing breaks if the service isn't up.
    meili_url: str = Field(default="http://meilisearch:7700", alias="MEILI_URL")
    meili_master_key: str = Field(default="", alias="MEILI_MASTER_KEY")
    meili_search_enabled: bool = Field(default=False, alias="MEILI_SEARCH_ENABLED")
    meili_index: str = Field(default="events", alias="MEILI_INDEX")

    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")

    llm_api_base_url: str = Field(default="http://176.109.82.96:5000", alias="LLM_API_BASE_URL")
    llm_timeout_seconds: float = Field(default=20.0, alias="LLM_TIMEOUT_SECONDS")
    # Service-wide cap on concurrent in-flight LLM requests (a shared Redis budget across api + worker).
    llm_max_concurrency: int = Field(default=20, alias="LLM_MAX_CONCURRENCY")

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
    # Timepad: independent-organiser events (curated cultural buckets only). The API needs a free
    # personal token; ingestion is a no-op until TIMEPAD_TOKEN is set, so it's off by default.
    timepad_base_url: str = "https://api.timepad.ru/v1"
    timepad_token: str = Field(default="", alias="TIMEPAD_TOKEN")
    # afisha.ru shows an IP-reputation CAPTCHA to RU datacenter IPs (our VK Cloud
    # egress). Prod routes afisha.ru through the WireGuard split-tunnel (→ a GCP
    # exit), which afisha does NOT challenge — so ingestion is enabled by default.
    afisha_enabled: bool = Field(default=True, alias="AFISHA_ENABLED")
    # Optional residential-proxy override for hosts without such a route (empty =
    # direct, relying on the tunnel routing).
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

    @model_validator(mode="after")
    def _fail_fast_on_prod_secrets(self):
        """Every field has a dev-friendly default, which means a misconfigured production deploy would
        silently run on insecure defaults (a dead bot, a guessable MinIO key). In production we refuse
        to start without the critical secret, and shout about the insecure defaults that aren't fatal."""
        if self.app_env != "production":
            return self
        if not self.telegram_bot_token:
            raise ValueError(
                "APP_ENV=production but TELEGRAM_BOT_TOKEN is empty — bot, reminders and digests would "
                "silently no-op. Set it (or unset APP_ENV for local)."
            )
        if self.minio_secret_key == "okrest-minio-secret":
            print("WARNING: MINIO_ROOT_PASSWORD is the insecure dev default in production", file=sys.stderr)
        if "afisha:afisha@" in self.database_url:
            print("WARNING: DATABASE_URL uses the default afisha:afisha credentials in production", file=sys.stderr)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
