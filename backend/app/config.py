import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    enable_scheduler: bool = os.environ.get("ENABLE_SCHEDULER", "false").lower() == "true"


settings = Settings()
