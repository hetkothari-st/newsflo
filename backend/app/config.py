import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    enable_scheduler: bool = os.environ.get("ENABLE_SCHEDULER", "false").lower() == "true"
    # DEV-ONLY default — this value is INSECURE and unsafe for production. Set
    # JWT_SECRET_KEY in the environment for any real deployment. (Same
    # optional-at-dev-time pattern as anthropic_api_key defaulting to "".)
    jwt_secret_key: str = os.environ.get("JWT_SECRET_KEY", "dev-insecure-secret-change-in-production")
    resend_api_key: str = os.environ.get("RESEND_API_KEY", "")


settings = Settings()
