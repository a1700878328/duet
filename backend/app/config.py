"""Application settings loaded from environment / .env (pydantic-settings)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Brain provider (DeepSeek by default; swap for Qwen fallback in one line).
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"

    # Auth. Override jwt_secret in production via env.
    jwt_secret: str = "dev-insecure-change-me-please-32bytes-minimum"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 30

    # Database. Async SQLAlchemy URL; swap engine to Postgres later.
    db_url: str = "sqlite+aiosqlite:///./duet.db"

    # History window fed to the brain.
    history_window: int = 30

    # Set true only to allow live brain calls in test/CI.
    allow_live_brain: bool = False


settings = Settings()
