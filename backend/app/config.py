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
    # News ingestion source -- see app/ingestion/indianapi.py. Now disabled
    # (not deleted, see app/scheduler.py), replaced by the thenewsapi block
    # below. The RSS-feed poller (app/ingestion/poller.py + sources.py) is
    # also still fully intact, just not wired into the scheduler either.
    indianapi_api_key: str = os.environ.get("INDIANAPI_API_KEY", "")
    # This key is capped at 500 requests/month. Explicit product decision to
    # poll at 1/min anyway (confirmed with the user, who understood the
    # tradeoff): at that rate the 500 budget is exhausted in ~8 hours, after
    # which IndianAPI ingestion goes dark (fetch_new_indianapi_articles
    # degrades to returning 0, per its "never raise, skip this cycle"
    # contract) until the key's quota resets next month.
    indianapi_poll_interval_minutes: int = int(os.environ.get("INDIANAPI_POLL_INTERVAL_MINUTES", "1"))
    # News ingestion source -- replaces IndianAPI (disabled, not deleted --
    # see app/scheduler.py). See docs/superpowers/specs/2026-07-20-
    # thenewsapi-ingestion-source-design.md.
    thenewsapi_api_key: str = os.environ.get("THENEWSAPI_API_KEY", "")
    # This key is capped at 100 requests/day. Explicit product decision to
    # poll at 1/min anyway (confirmed with the user, who understood the
    # tradeoff after being shown the math): at that rate the 100/day budget
    # is exhausted in ~100 minutes, after which thenewsapi ingestion goes
    # dark (fetch_new_thenewsapi_articles degrades to returning 0, per its
    # "never raise, skip this cycle" contract) until the cap resets at
    # midnight (thenewsapi's reset timezone) -- this repeats every day,
    # not a one-time cost like IndianAPI's monthly cap above. Same
    # documented-tradeoff pattern as indianapi_poll_interval_minutes.
    thenewsapi_poll_interval_minutes: int = int(os.environ.get("THENEWSAPI_POLL_INTERVAL_MINUTES", "1"))
    # News ingestion source -- replaces thenewsapi (disabled, not deleted --
    # see app/scheduler.py). thenewsapi's 100/day cap kept exhausting
    # mid-day in production; Finnhub's free tier is 60 calls/min. See
    # docs/superpowers/specs/2026-07-21-finnhub-ingestion-source-design.md.
    finnhub_api_key: str = os.environ.get("FINNHUB_API_KEY", "")
    finnhub_poll_interval_minutes: int = int(os.environ.get("FINNHUB_POLL_INTERVAL_MINUTES", "1"))
    brandfetch_client_id: str = os.environ.get("BRANDFETCH_CLIENT_ID", "")
    # Empty disables the live-price feature entirely (same convention as
    # brandfetch_client_id) -- local dev/CI never opens an outbound
    # WebSocket connection unless this is explicitly set.
    zerodha_hub_url: str = os.environ.get("ZERODHA_HUB_URL", "")


settings = Settings()

# --- Market-impact measurement constants (docs/NEWS_IMPACT_APP_SPEC.md §4) ---
# Not environment-backed: these are product/algorithm constants tuned via
# CAR back-validation (spec §4.6, a later phase), not per-deployment
# secrets -- unlike every Settings field above. Every intensity/verdict/
# cap-tier function in app/market/ reads its weights and thresholds from
# here, never hardcodes them (spec §4.2, §10).

# Live-feed intensity weights (spec §4.2) -- must sum to 1.0. The advisory-
# tier weight profile (adds a fundamental_score term) is out of scope until
# the FundamentalEstimate/RIA-advisory phase.
INTENSITY_WEIGHTS_LIVE = {"excess": 0.55, "volume": 0.25, "breadth": 0.20}

# Intensity band thresholds (spec §4.2): >=75 High, 50-74 Moderate, <50 Low.
INTENSITY_BAND_HIGH = 75
INTENSITY_BAND_MODERATE = 50

# A move (as % excess) at or above this magnitude is "meaningful" for
# breadth counting (spec §4.4) -- a linked stock that barely twitched
# doesn't count as part of the event's spread.
BREADTH_MEANINGFUL_MOVE_PCT = 1.0

# Verdict threshold (spec §4.3): |excess_move_pct| at or above this ->
# COMPANY_SPECIFIC, else SECTOR_WIDE (when not UNCONFIRMED). Starting value;
# retune against CAR outcomes (spec §4.6) once that data exists.
VERDICT_EXCESS_THRESHOLD_PCT = 2.0

# AMFI-style cap-tier rank cutoffs (spec §4.5): rank 1-100 by market cap ->
# LARGE, 101-250 -> MID, rest -> SMALL. Ranks are recomputed from live
# Company.market_cap every call -- never a hardcoded company list.
AMFI_LARGE_CAP_RANK_CUTOFF = 100
AMFI_MID_CAP_RANK_CUTOFF = 250
