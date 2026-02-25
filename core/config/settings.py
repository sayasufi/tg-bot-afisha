from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    api_port: int = Field(default=8000, alias="API_PORT")
    database_url: str = Field(alias="DATABASE_URL")
    sync_database_url: str = Field(alias="SYNC_DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")

    celery_broker_url: str = Field(alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(alias="CELERY_RESULT_BACKEND")

    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    yandexgpt_api_key: str = Field(default="", alias="YANDEXGPT_API_KEY")
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")

    yandex_geocoder_key: str = Field(default="", alias="YANDEX_GEOCODER_KEY")
    nominatim_base_url: str = Field(default="https://nominatim.openstreetmap.org", alias="NOMINATIM_BASE_URL")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_webapp_url: str = Field(default="", alias="TELEGRAM_WEBAPP_URL")

    telethon_api_id: int | None = Field(default=None, alias="TELETHON_API_ID")
    telethon_api_hash: str = Field(default="", alias="TELETHON_API_HASH")
    telethon_session: str = Field(default="afisha_session", alias="TELETHON_SESSION")

    timepad_base_url: str = Field(default="https://api.timepad.ru/v1", alias="TIMEPAD_BASE_URL")

    default_city: str = Field(default="Moscow", alias="DEFAULT_CITY")
    default_country: str = Field(default="RU", alias="DEFAULT_COUNTRY")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
