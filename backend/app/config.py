import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    openrouter_api_key: str = os.environ.get("OPENROUTER_API_KEY", "")
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    groq_api_key: str = os.environ.get("GROQ_API_KEY", "")
    # Comma-separated additional Groq keys, rotated to automatically when the
    # currently-active key hits a rate limit (see RotatingClient). Empty by
    # default -- a single groq_api_key alone works fine, this only adds
    # failover capacity when more keys are available.
    groq_api_keys_extra: str = os.environ.get("GROQ_API_KEYS_EXTRA", "")

    @property
    def groq_api_keys(self) -> list[str]:
        keys = [self.groq_api_key] if self.groq_api_key else []
        keys += [k.strip() for k in self.groq_api_keys_extra.split(",") if k.strip()]
        return keys
    # A Groq key from a SEPARATE account (its own, independent per-minute
    # token quota bucket) -- unlike groq_api_keys_extra above, which are
    # same-org keys that share ONE bucket with groq_api_key and only help
    # with failover, not real parallel throughput. Used specifically to run
    # translation across two independent quota buckets at once (see
    # translation/groq_translator.py's build_translation_clients).
    translation_groq_api_key_2: str = os.environ.get("TRANSLATION_GROQ_API_KEY_2", "")

    @property
    def translation_groq_api_keys(self) -> list[str]:
        keys = [self.groq_api_key] if self.groq_api_key else []
        if self.translation_groq_api_key_2:
            keys.append(self.translation_groq_api_key_2)
        return keys
    enable_scheduler: bool = os.environ.get("ENABLE_SCHEDULER", "false").lower() == "true"
    poll_interval_minutes: int = int(os.environ.get("POLL_INTERVAL_MINUTES", "2"))
    translation_interval_minutes: int = int(os.environ.get("TRANSLATION_INTERVAL_MINUTES", "5"))
    # DEV-ONLY default — this value is INSECURE and unsafe for production. Set
    # JWT_SECRET_KEY in the environment for any real deployment. (Same
    # optional-at-dev-time pattern as anthropic_api_key defaulting to "".)
    jwt_secret_key: str = os.environ.get("JWT_SECRET_KEY", "dev-insecure-secret-change-in-production")
    resend_api_key: str = os.environ.get("RESEND_API_KEY", "")
    brandfetch_client_id: str = os.environ.get("BRANDFETCH_CLIENT_ID", "")


settings = Settings()
