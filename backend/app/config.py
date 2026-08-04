import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    gemini_api_key: str = os.environ.get("GEMINI_API_KEY", "")
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
    # Mark the stable prefix of every analysis prompt (the system prompt and
    # the tool schema, identical across calls) with the active provider's
    # prompt-caching mechanism -- see app.analysis.claude_client. Caching
    # changes billing only: the model receives byte-identical input and
    # returns the same output either way, so this defaults ON. Set
    # PROMPT_CACHE_ENABLED=false to turn it off without a code change if a
    # provider ever starts rejecting the markers.
    prompt_cache_enabled: bool = os.environ.get("PROMPT_CACHE_ENABLED", "true").lower() == "true"
    # Deterministic rule pass in front of the per-article relevance LLM call
    # (app.filtering.prefilter). "shadow" (the default) runs the rules and
    # logs what they WOULD reject without acting on it -- the only safe way
    # to start, since the cost of a wrong reject is a real market story
    # silently never reaching the feed. "enforce" acts on the verdict.
    # "off" skips the rules entirely.
    relevance_prefilter_mode: str = os.environ.get("RELEVANCE_PREFILTER_MODE", "shadow")
    # Comma-separated LLM call names to route to the CHEAP model tier (see
    # LLM_TIERABLE_CALLS below and app.analysis.claude_client). Empty by
    # default, and that default is the point: a call only belongs here once
    # a strong-vs-cheap output diff on real articles has shown the cheap
    # model is equivalent for it. Names in LLM_PROTECTED_CALLS are ignored
    # even if listed -- those calls ARE the product's output quality.
    llm_cheap_tier_calls: str = os.environ.get("LLM_CHEAP_TIER_CALLS", "")
    # Persist one llm_call_usage row per LLM call (tokens, model, tier,
    # cache hits). Off by default so ordinary runs and the test suite don't
    # write rows nobody reads; the measurement harness turns it on. The
    # structured log line is emitted either way.
    llm_usage_db_logging: bool = os.environ.get("LLM_USAGE_DB_LOGGING", "false").lower() == "true"
    # "inline" (default) runs the four refinement calls inside the analysis
    # run that created the alert, as they always have. "deferred" persists
    # the alert without them and leaves a later batch pass
    # (app.analysis.refinement.run_pending_refinements) to fill them in, so
    # refinement stops competing with the analysis pipeline for rate-limit
    # headroom and can be batched. Nothing user-facing blocks on refinement
    # either way -- the fields it writes are already nullable everywhere
    # they are read.
    refinement_mode: str = os.environ.get("REFINEMENT_MODE", "inline")
    # How many pending alerts one deferred pass refines. Bounded so a
    # backlog is worked off over several ticks instead of one pass burning
    # a whole quota.
    refinement_batch_limit: int = int(os.environ.get("REFINEMENT_BATCH_LIMIT", "20"))
    refinement_interval_minutes: int = int(os.environ.get("REFINEMENT_INTERVAL_MINUTES", "5"))
    # Gates app.companies.matching.matcher (spec §8). Set to "false" to
    # restore the pre-rebuild substring resolver without a deploy.
    use_alias_matcher: bool = os.environ.get("USE_ALIAS_MATCHER", "true").lower() == "true"


settings = Settings()

# --- LLM prompt caching (docs: cost-optimization phase 2) ---
# Anthropic's cache-control type. "ephemeral" is their 5-minute TTL, which
# is the right fit here: a single article's cascade stages fire seconds
# apart, so every stage after the first hits a warm cache, and nothing is
# held past the run. Kept here (not hardcoded in the client) so a longer
# TTL can be adopted without touching the adapter.
PROMPT_CACHE_CONTROL = {"type": "ephemeral"}

# --- LLM model tiering (docs: cost-optimization phase 4) ---
LLM_TIER_REASONING = "reasoning"
LLM_TIER_CHEAP = "cheap"

# Which concrete model each provider serves a tier with. The client layer
# only ever acts on LLM_TIER_CHEAP: a reasoning-tier call is sent exactly as
# its call site built it, so with the default configuration below nothing
# about any request changes. Names live here rather than in the adapters so
# swapping a tier's model is a config edit.
LLM_TIER_MODELS = {
    "gemini": {LLM_TIER_REASONING: "gemini-flash-latest", LLM_TIER_CHEAP: "gemini-flash-lite-latest"},
    "groq": {LLM_TIER_REASONING: "llama-3.3-70b-versatile", LLM_TIER_CHEAP: "openai/gpt-oss-20b"},
    "anthropic": {LLM_TIER_REASONING: "claude-sonnet-4-5", LLM_TIER_CHEAP: "claude-haiku-4-5-20251001"},
}

# Calls that stay on the strongest model no matter what the configuration
# says. "extract_facts" is the one full-article read and everything
# downstream reasons from its output; "identify_companies" decides which
# companies are affected and why, which IS the thing this product sells.
# Saving money on either is not a trade worth making, so resolve_tier
# refuses to make it.
LLM_PROTECTED_CALLS = frozenset({"extract_facts", "identify_companies"})

# Calls that MAY move to the cheap tier -- structured extraction and
# formatting of already-decided facts, plus a binary classification.
# Eligible is not the same as approved: each one needs a strong-vs-cheap
# diff on real articles before its name goes in LLM_CHEAP_TIER_CALLS.
LLM_TIERABLE_CALLS = frozenset({
    "identify_sectors", "generate_edges", "classify_relevance",
    "event_summary", "impact_whys", "ripple_layers", "timeline_effects",
})


def resolve_tier(call_name: str) -> str:
    """The model tier a given LLM call should run on. Defaults to the
    reasoning tier for everything -- a call is downgraded only when it is
    both eligible and explicitly listed in LLM_CHEAP_TIER_CALLS, and never
    when it is protected."""
    if call_name in LLM_PROTECTED_CALLS:
        return LLM_TIER_REASONING
    requested = {name.strip() for name in settings.llm_cheap_tier_calls.split(",") if name.strip()}
    if call_name in requested and call_name in LLM_TIERABLE_CALLS:
        return LLM_TIER_CHEAP
    return LLM_TIER_REASONING


# --- LLM cost accounting (docs: cost-optimization phase 6) ---
# USD per million tokens, keyed by model name then "input"/"output"/
# "cache_read". Intentionally EMPTY by default: provider list prices change,
# and a stale number baked in here would produce a confident, wrong cost
# report. Fill it from the provider's current pricing page for the models
# actually configured above, e.g.
#
#   LLM_MODEL_PRICING_USD_PER_MTOK = {
#       "gemini-flash-latest": {"input": 0.30, "output": 2.50, "cache_read": 0.075},
#   }
#
# The measurement harness always reports real token counts; it reports cost
# only for models priced here, and names the ones it had no price for.
LLM_MODEL_PRICING_USD_PER_MTOK: dict[str, dict[str, float]] = {}

# --- Relevance pre-filter rules (docs: cost-optimization phase 3) ---
# The pre-filter's whole job is to skip the relevance LLM call on articles
# that are UNAMBIGUOUSLY not market news. It is deliberately lopsided: a
# wrongly-admitted article costs one cheap classification call, while a
# wrongly-rejected one loses a real story from the feed forever. So the
# rules below only ever fire together with the veto above them, and
# anything they are not certain about goes to the LLM.

# If ANY of these appears anywhere in an article (headline or body), the
# pre-filter admits it no matter what else matched -- this is the veto that
# keeps the rules honest. Deliberately over-broad: "price", "deal" and
# "crore" catch enormous amounts of ordinary prose, and that is the point.
# A market story that reads as noise by its headline alone (a promoter
# arrest, a plant fire, a stampede at a listing) almost always carries one
# of these somewhere in its body.
RELEVANCE_PREFILTER_MARKET_SIGNALS = [
    # money and magnitude
    "₹", "$", "€", "%", "crore", "lakh", "billion", "million", "trillion",
    "bps", "basis point", "per cent", "percent",
    # markets and instruments
    "stock", "share", "equity", "equities", "bourse", "sensex", "nifty", "bse", "nse",
    "index", "ipo", "listing", "listed", "delisting", "dividend", "buyback", "bond",
    "yield", "derivative", "futures", "commodity", "commodities", "currency", "rupee",
    "dollar", "forex", "exchange rate",
    # company financials and corporate actions
    "earnings", "revenue", "profit", "margin", "ebitda", "guidance", "quarterly",
    "results", "valuation", "turnover", "order book", "contract", "deal", "merger",
    "acquisition", "acquire", "stake", "promoter", "shareholder", "investor",
    "funding", "fundraise", "capex", "expansion", "layoff", "hiring", "restructuring",
    "insolvency", "bankruptcy", "default", "downgrade", "upgrade", "rating",
    # people whose news moves a company
    "ceo", "chairman", "chief executive", "managing director", "cfo", "board of directors",
    # policy, regulators and macro
    "rbi", "sebi", "irdai", "trai", "fed", "ecb", "imf", "gst", "tax", "tariff", "duty",
    "export", "import", "trade", "gdp", "inflation", "cpi", "wpi", "deficit", "subsidy",
    "policy", "regulation", "regulator", "licence", "license", "sanction", "budget",
    "repo rate", "interest rate", "lending rate", "monetary",
    # real-economy inputs a story can move
    "price", "pricing", "supply", "demand", "output", "production", "plant", "factory",
    "crude", "oil", "gas", "petrol", "diesel", "gold", "silver", "steel", "cement",
    "coal", "metal", "power", "electricity", "semiconductor", "chip",
    "bank", "loan", "credit", "npa", "insurance", "premium",
    "monsoon", "rainfall", "crop", "harvest", "sowing", "fertiliser", "fertilizer",
    "economy", "economic", "industry", "sector", "business", "company", "firm",
    # Inflections the matcher's own optional-plural rule cannot reach (it
    # appends "s"/"es" to the forms above, so anything with a stem change
    # or a different suffix has to be spelled out).
    "companies", "industries", "economies", "trading", "banking", "lending",
    "borrowing", "manufacturing", "investment", "financial", "finance",
]

# Regexes matched against the HEADLINE only. A body mention is never enough
# to reject -- a story about a sponsorship deal legitimately says "cricket"
# in its body, and a plant-closure story legitimately says "accident".
# These describe article FORMATS that are never market news, not topics
# that merely tend not to be. Anything arguable (weather, which this system
# treats as a first-class event type via monsoon_weather; box-office, which
# is media-company revenue; an executive's death, which moves a stock) is
# deliberately absent.
RELEVANCE_PREFILTER_NOISE_PATTERNS = [
    r"\b(horoscope|rashifal|zodiac|astrolog\w*|numerolog\w*|tarot|panchang)\b",
    r"\b(recipe|recipes)\b",
    r"\b(lottery result|lucky draw|sudoku|crossword|word\s?le|quiz answer)\b",
    r"\b(viral video|goes viral|caught on camera|watch video|netizens|trolled|meme)\b",
    r"\b(weight loss|skin\s?care|beauty tips|home remed\w*|diet plan|yoga (poses|asanas))\b",
    r"\b(wedding|haldi|sangeet|honeymoon|dating rumou?rs|girlfriend|boyfriend|red carpet)\b",
    r"\b(wicket|wickets|innings|batting|bowler|century stand|man of the match|"
    r"grand slam|wimbledon|goalkeeper|penalty shootout|half.century)\b",
    r"\b(murder|rape|molest\w*|kidnap\w*|stabb(ed|ing)|assaulted|"
    r"road accident|bus (crash|collision|accident)|hit.and.run)\b",
    r"\b(obituary|death anniversary|condolence\w*|funeral)\b",
]

# --- Market-impact measurement constants (docs/NEWS_IMPACT_APP_SPEC.md §4) ---
# Not environment-backed: these are product/algorithm constants tuned via
# CAR back-validation (spec §4.6, a later phase), not per-deployment
# secrets -- unlike every Settings field above. Every intensity/verdict/
# cap-tier function in app/market/ reads its weights and thresholds from
# here, never hardcodes them (spec §4.2, §10).

# Six-signal composite intensity weights (spec v2 §4.2) -- the full
# advisory-tier profile. The live-feed tier has no fundamental signal, and
# older MarketMove rows may lack delivery/materiality/vol_norm values --
# compute_intensity renormalizes the weights of whichever signals are
# actually present so they sum to 1 (spec §4.2: "Live-feed tier (no
# fundamental): renormalize the other five to sum to 1").
INTENSITY_WEIGHTS = {
    "excess": 0.28,
    "volume": 0.12,
    "delivery": 0.15,
    "materiality": 0.25,
    "vol_norm": 0.10,
    "fundamental": 0.10,
}

# -- COMMENTED OUT (superseded by INTENSITY_WEIGHTS above, spec v2 §4.2's
# six-signal blend; breadth is an event-level metric, no longer an
# intensity component):
# INTENSITY_WEIGHTS_LIVE = {"excess": 0.55, "volume": 0.25, "breadth": 0.20}

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

# CAR (Cumulative Abnormal Return, spec §4.6) review thresholds.
CAR_FLAT_THRESHOLD_PCT = 0.5  # |car_pct| below this counts as FLAT (neither held nor reversed)
CAR_SUMMARY_SAMPLE_THRESHOLD = 5  # matches calibration/track_record.py's WIN_RATE_SAMPLE_THRESHOLD convention

# AMFI-style cap-tier rank cutoffs (spec §4.5): rank 1-100 by market cap ->
# LARGE, 101-250 -> MID, rest -> SMALL. Ranks are recomputed from live
# Company.market_cap every call -- never a hardcoded company list.
AMFI_LARGE_CAP_RANK_CUTOFF = 100
AMFI_MID_CAP_RANK_CUTOFF = 250

# MICRO cutoff. Spec v2 §4.5 originally chose a rupee floor; that was an
# invented boundary. Replaced by NSE's PUBLISHED index methodology: ranks
# 501-750 are the Nifty Microcap 250 universe, so rank 501+ is MICRO.
# See docs/superpowers/specs/2026-08-03-stock-universe-cap-tiers-design.md §7.2.
MICRO_CAP_RANK_CUTOFF = 500

# Staleness thresholds (spec §6.3). Past these, a value is reported stale
# and the derived cap tier is WITHHELD rather than computed from old caps
# and presented as current -- same discipline as app.market.measure
# returning measurement_status='no_data' instead of a number.
UNIVERSE_MAX_AGE_DAYS = 7
MARKET_CAP_MAX_AGE_DAYS = 30
CLASSIFICATION_MAX_AGE_DAYS = 180
AMFI_MAX_AGE_DAYS = 240

# Liquidity tier thresholds (spec v2 §4.6): derived from 20-day average
# traded value (close x volume, same unit as prices x shares). LOW liquidity
# on a small/micro cap is a risk cue, not decoration.
LIQUIDITY_HIGH_AVG_TRADED_VALUE = 500_000_000.0  # >= -> HIGH
LIQUIDITY_MODERATE_AVG_TRADED_VALUE = 50_000_000.0  # >= -> MODERATE, else LOW

# Delivery-percentage warning threshold (spec v2 §4.2, §6): delivery_pct
# below this fires the "much of this move was intraday speculation" warning.
LOW_DELIVERY_WARNING_PCT = 50.0

# Unusual-activity discovery threshold (spec v2 §6 path 3): a small/micro
# cap whose day volume is at least this multiple of its own 20-day average
# qualifies for the "unusual activity" tab.
UNUSUAL_VOLUME_MULTIPLE = 2.0

# An image_url attached to at least this many DIFFERENT articles is
# publisher boilerplate (a logo/default banner), not a story photo -- see
# app.ingestion.image_filter. Real news photos are unique per story.
GENERIC_IMAGE_REPEAT_THRESHOLD = 3
