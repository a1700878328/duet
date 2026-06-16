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

    # Live media switches for local debugging.
    media_generation_enabled: bool = True
    voice_generation_enabled: bool = True
    voice_provider: str = "auto"

    # ElevenLabs Voice Design / TTS. If eleven_api_key is empty, local dev can
    # point at a file such as ~/Desktop/eleven.txt without committing secrets.
    eleven_api_base: str = "https://api.elevenlabs.io"
    eleven_api_key: str = ""
    eleven_api_key_file: str = "~/Desktop/eleven.txt"
    eleven_voice_design_model: str = "eleven_multilingual_ttv_v2"
    eleven_tts_model: str = "eleven_v3"
    eleven_output_format: str = "mp3_44100_128"
    eleven_design_loudness: float = 0.35
    eleven_design_guidance_scale: float = 5.0
    eleven_clone_design_preview: bool = True
    anime_voice_style_bias: str = (
        "Original Japanese anime / visual novel character voice, seiyuu-inspired "
        "but not imitating any real person. Expressive, melodic pitch movement, "
        "clear youthful tone, cute charm, lively emotional acting, crisp consonants, "
        "natural breath, playful intonation, suitable for an anime RPG character."
    )

    # Fish Audio S2-Pro.
    fish_api_base: str = "https://api.fish.audio"
    fish_api_key: str = ""
    fish_tts_model: str = "s2-pro"
    fish_default_reference_id: str = ""
    fish_female_reference_id: str = "8ef4a238714b45718ce04243307c57a7"
    fish_male_reference_id: str = "802e3bc2b27e49c2995d23ef70e6ac89"
    fish_tts_format: str = "mp3"
    fish_tts_temperature: float = 0.55
    fish_tts_top_p: float = 0.7
    fish_tts_chunk_length: int = 300
    fish_tts_speed: float = 1.0
    fish_tts_volume: float = 0.0
    fish_performance_tags_enabled: bool = True


settings = Settings()
