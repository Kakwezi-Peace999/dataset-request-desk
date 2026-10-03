"""Central configuration, read from environment variables (12-factor style)."""
import os

DEFAULT_SECRET = "dev-only-change-me"


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://drd:drd@localhost:5432/drd")
    secret_key: str = os.getenv("SECRET_KEY", DEFAULT_SECRET)
    access_token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "480"))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "50"))
    # Import sanity limit: episodes are short clips, anything above this is treated as a data error.
    max_duration_seconds: int = int(os.getenv("MAX_DURATION_SECONDS", "3600"))
    seed_dir: str = os.getenv("SEED_DIR", "seed")
    seed_episodes: bool = os.getenv("SEED_EPISODES", "0") == "1"


settings = Settings()
