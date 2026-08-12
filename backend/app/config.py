import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    gemini_api_key: str = os.environ.get("GEMINI_API_KEY", "")
    # PAID Gemini key, spent ONLY on the protected calls (extract_facts,
    # identify_companies -- see LLM_PROTECTED_CALLS below and
    # claude_client.CallRoutedClient). Empty = no routing, everything rides
    # the free chain exactly as before. Never put this key in
    # GEMINI_API_KEY: that would burn paid quota on every cheap
    # high-volume call (relevance gate, summaries) too.
    gemini_paid_api_key: str = os.environ.get("GEMINI_PAID_API_KEY", "")
    # HARD daily budget on the paid key, counted in ARTICLES (not calls):
    # only this many articles per day may route their protected calls to
    # the paid Gemini chain; every article past the cap -- and every
    # article from a provider not in gemini_paid_providers -- runs on the
    # free chain no matter what. Enforced in
    # app/pipeline.py.select_analysis_client, accounted retry-proof in the
    # gemini_paid_usage table.
    gemini_paid_daily_article_budget: int = int(os.environ.get("GEMINI_PAID_DAILY_ARTICLE_BUDGET", "5"))
    # Comma-separated Article.provider slugs eligible for the paid key.
    # Default: only Pulse by Zerodha (curated financial news, every item
    # analysis-worthy). Empty string = no provider is eligible = the paid
    # key is never used regardless of the budget.
    gemini_paid_providers: str = os.environ.get("GEMINI_PAID_PROVIDERS", "pulse_zerodha")

    @property
    def gemini_paid_provider_set(self) -> set[str]:
        return {s.strip() for s in self.gemini_paid_providers.split(",") if s.strip()}
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

    # Comma-separated Gemini keys DEDICATED to supply-link extraction, so
    # the rating-rationale backlog drains without touching the analysis
    # pipeline's shared Groq quota (user-provisioned 2026-08-07; see
    # app.companies.supply_links.llm for the rotation semantics). Empty by
    # default -- extraction then rides the shared chain, as before.
    supply_gemini_api_keys_raw: str = os.environ.get("SUPPLY_GEMINI_API_KEYS", "")

    @property
    def supply_gemini_api_keys(self) -> list[str]:
        return [k.strip() for k in self.supply_gemini_api_keys_raw.split(",") if k.strip()]
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
    # Lets a non-production deployment (e.g. a UI-preview service sharing
    # the production database) opt back in to demo-seeded feed stories.
    # Production leaves this unset: demo-marked articles never reach its
    # feed regardless of what sits in the shared database.
    allow_demo_feed: bool = os.environ.get("ALLOW_DEMO_FEED", "false").lower() == "true"
    poll_interval_minutes: int = int(os.environ.get("POLL_INTERVAL_MINUTES", "2"))
    translation_interval_minutes: int = int(os.environ.get("TRANSLATION_INTERVAL_MINUTES", "5"))
    # DEV-ONLY default — this value is INSECURE and unsafe for production. Set
    # JWT_SECRET_KEY in the environment for any real deployment. (Same
    # optional-at-dev-time pattern as anthropic_api_key defaulting to "".)
    jwt_secret_key: str = os.environ.get("JWT_SECRET_KEY", "dev-insecure-secret-change-in-production")
    resend_api_key: str = os.environ.get("RESEND_API_KEY", "")
    # News ingestion source -- now app/ingestion/providers/indianapi.py,
    # scheduled through the provider registry (IngestionSource rows).
    indianapi_api_key: str = os.environ.get("INDIANAPI_API_KEY", "")
    # SEED OVERRIDE ONLY: per-source cadence lives in
    # IngestionSource.poll_interval_minutes now. This env var (like the
    # finnhub one below) is read once, when ensure_registry_rows first
    # seeds the source's row on a fresh DB -- set it to carry a
    # deployment's existing cadence through the upgrade; edit the DB row
    # to change cadence afterwards. Default None = use the provider's
    # code default (90 min: the 500 req/month cap fits ~16 polls/day --
    # the historical 1/min cadence burned the whole budget in ~8 hours).
    indianapi_poll_interval_minutes: int | None = (
        int(os.environ["INDIANAPI_POLL_INTERVAL_MINUTES"]) if os.environ.get("INDIANAPI_POLL_INTERVAL_MINUTES") else None
    )
    # thenewsapi (app/ingestion/thenewsapi.py) is superseded and unwired --
    # its 100 req/day cap kept exhausting mid-day (see docs/superpowers/
    # specs/2026-07-21-finnhub-ingestion-source-design.md). Module and key
    # kept for reference; there is no registry provider for it.
    thenewsapi_api_key: str = os.environ.get("THENEWSAPI_API_KEY", "")
    # News ingestion source -- now app/ingestion/providers/finnhub.py,
    # scheduled through the provider registry. Free tier is 60 calls/min;
    # the provider's default cadence is 1/min (2 calls per cycle).
    finnhub_api_key: str = os.environ.get("FINNHUB_API_KEY", "")
    # SEED OVERRIDE ONLY -- same semantics as
    # indianapi_poll_interval_minutes above.
    finnhub_poll_interval_minutes: int | None = (
        int(os.environ["FINNHUB_POLL_INTERVAL_MINUTES"]) if os.environ.get("FINNHUB_POLL_INTERVAL_MINUTES") else None
    )
    # --- Multi-source ingestion layer (app/ingestion/collector.py) ---
    # Marketaux free tier: 3 articles/request, 100 requests/day. The
    # provider's default 15-minute cadence = 96 req/day, just under the cap;
    # anything faster exhausts the budget mid-day exactly the way thenewsapi
    # did (see its comment above). Upgrade the plan before shortening this.
    marketaux_api_key: str = os.environ.get("MARKETAUX_API_TOKEN", os.environ.get("MARKETAUX_API_KEY", ""))
    # Benzinga REST /api/v2/news. Quota undocumented for this key -- the
    # collector's per-source circuit breaker backs off automatically on
    # sustained 429s, so a too-fast interval degrades gracefully instead of
    # hammering the API.
    benzinga_api_key: str = os.environ.get("BENZINGA_API_KEY", "")
    # Comma-separated provider slugs whose IngestionSource row seeds
    # enabled=1 on FIRST boot against a database that has no row for them
    # yet (see app/ingestion/providers/registry.py for the slug list).
    # Defaults to "finnhub" so a deployment that predates the multi-source
    # layer keeps exactly its current behavior after upgrading; the
    # multi-source service sets the full list in its env. After first seed
    # the DB row's `enabled` is the source of truth -- this setting never
    # overrides an existing row.
    ingestion_enabled_sources: str = os.environ.get("INGESTION_ENABLED_SOURCES", "finnhub")
    # Gemini "thinking" budget. gemini-2.5-flash reasons internally before
    # answering and bills those hidden tokens as OUTPUT (the expensive
    # direction) -- often 500-2,000 per call, measured as roughly half the
    # paid bill on 2026-08-10. UNSET (default) omits the field entirely --
    # the provider's default behavior, the only configuration verified
    # working with tool-forced calls. Set 0 to disable thinking (cost
    # halves) ONLY after verifying against a live key: on 2026-08-10 a
    # thinkingBudget=0 deploy coincided with Gemini silently refusing
    # identify_companies calls, unproven but unexcluded as the cause.
    gemini_thinking_budget: int | None = (
        int(os.environ["GEMINI_THINKING_BUDGET"]) if os.environ.get("GEMINI_THINKING_BUDGET") else None
    )
    # Minimum spacing between consecutive Groq calls, process-wide. The
    # cascade's cheap stages run back-to-back and a single article's calls
    # (~3-4k tokens each) alone saturate gpt-oss-20b's 8,000 TPM ceiling --
    # measured live 2026-08-10: one uncontested article 429'd itself. 0
    # (default) preserves existing behavior; ~20-25s lets a full cascade
    # complete on free-tier Groq at ~2-3 min/article.
    groq_min_call_interval_seconds: float = float(os.environ.get("GROQ_MIN_CALL_INTERVAL_SECONDS", "0"))
    # Exchange-announcement noise gate (app/filtering/exchange_noise.py) --
    # NSE/BSE corporate filings are dominated by mechanically produced
    # non-news (NAV declarations, trading-window closures, newspaper-copy
    # attachments). Same shadow/enforce/off semantics as
    # relevance_prefilter_mode above, and shadow-by-default for the same
    # reason: the cost of a wrong reject is a real disclosure silently
    # missing from the feed. The multi-source service runs "enforce".
    exchange_noise_mode: str = os.environ.get("EXCHANGE_NOISE_MODE", "shadow")

    @property
    def ingestion_enabled_source_set(self) -> set[str]:
        return {s.strip() for s in self.ingestion_enabled_sources.split(",") if s.strip()}
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

    # --- Impact-graph v3 model routing (spec 2026-08-11, docs 1-4) ---
    # Stage-typed Gemini models for the causal impact graph. All defaults
    # verified live against the paid key's ListModels on 2026-08-11 --
    # change via env, never hardcode elsewhere. The reasoning model owns
    # EVERY quality-critical stage for protected articles (shocks, graph,
    # companies, ripples, verification, ranking); the fact model serves
    # extraction only; the fallback model is the DEGRADED reasoning tier
    # (never silently equivalent -- see analysis_quality on Alert).
    gemini_fact_model: str = os.environ.get("GEMINI_FACT_MODEL", "gemini-3.5-flash-lite")
    gemini_reasoning_model: str = os.environ.get("GEMINI_REASONING_MODEL", "gemini-3.1-pro-preview")
    gemini_summary_model: str = os.environ.get("GEMINI_SUMMARY_MODEL", "gemini-3.6-flash")
    gemini_fallback_model: str = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.6-flash")
    groq_aux_model: str = os.environ.get("GROQ_AUX_MODEL", "llama-3.3-70b-versatile")
    # Per-stage Gemini model overrides, e.g.
    # "ripple_discovery=gemini-3.6-flash,map_companies=gemini-3.6-flash".
    # Empty (default) = every reasoning stage rides gemini_reasoning_model.
    # The hybrid cost lever (2026-08-11): move a PROVEN-equivalent stage to
    # Flash without touching the others -- never a silent global downgrade.
    gemini_stage_model_overrides: str = os.environ.get("GEMINI_STAGE_MODEL_OVERRIDES", "")
    # Narrow-tier single-call mode (validated manually 2026-08-11 via the
    # v2.1 anti-omission prompt): narrow articles run facts + ONE graph
    # call + ONE batched companies call instead of 6-8 staged calls.
    # Verification escalates risk-based. Broad events always stay staged.
    impact_narrow_single_call: bool = os.environ.get("IMPACT_NARROW_SINGLE_CALL", "true").lower() == "true"

    @property
    def gemini_stage_model_override_map(self) -> dict[str, str]:
        result = {}
        for pair in self.gemini_stage_model_overrides.split(","):
            if "=" in pair:
                stage, model = pair.split("=", 1)
                if stage.strip() and model.strip():
                    result[stage.strip()] = model.strip()
        return result
    # Recursive expansion hard safety cap (spec: MAX_CAUSAL_DEPTH = 5).
    max_causal_depth: int = int(os.environ.get("MAX_CAUSAL_DEPTH", "5"))
    # Per-article Gemini budgets. 0 = unlimited (budget disabled). Cost is
    # estimated from LLM_MODEL_PRICING_USD_PER_MTOK when priced, else only
    # token ceilings apply. Exceeding a budget stops further expansion and
    # marks the analysis budget_exhausted -- it never silently continues.
    # Defaults tightened 2026-08-11 after the first live run: one wide event
    # measured 74k in / 69k out on the Pro model under the old 250k/60k
    # ceilings -- roughly $1-1.6 for a single article. These caps bound the
    # damage; expansion stops (quality=budget_exhausted) rather than
    # overrunning.
    gemini_max_input_tokens_per_article: int = int(os.environ.get("GEMINI_MAX_INPUT_TOKENS_PER_ARTICLE", "100000"))
    gemini_max_output_tokens_per_article: int = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS_PER_ARTICLE", "24000"))
    gemini_max_cost_per_article_usd: float = float(os.environ.get("GEMINI_MAX_COST_PER_ARTICLE", "0"))


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

# -- Event volatility ranges (subsystem D, spec 2026-08-05) --------------
# Minimum measured events before a range is stored/shown at each level.
# Below both: no row, nothing shown -- omit rather than fabricate.
EVENT_VOL_COMPANY_MIN_EVENTS = 3
EVENT_VOL_SECTOR_MIN_EVENTS = 5

# -- Supply links from rating rationales (spec 2026-08-06) ---------------
# Per-document caps: beyond three names a rationale is listing the sector,
# not counterparties (and the user asked for brief).
SUPPLY_LINK_MAX_PER_RELATION = 3
# Prompt-block budget for the KNOWN RELATIONSHIPS grounding section. The
# per-candidate description block that once measured 60.8k chars across
# 360 candidates broke both models' TPM ceilings -- this block is capped
# hard and covers event companies only.
SUPPLY_PROMPT_MAX_LINES = 8
# Trimmed 700 -> 500 (2026-08-06 review): with links present the assembled
# cascade company prompt measured 6,657-7,165 tokens against
# COMPANY_PROMPT_TOKEN_BUDGET=6,500 (see cascade._identify_companies and
# tests/test_prompt_budget.py) -- gpt-oss-20b's 8,000 TPM ceiling has no
# margin left for a full 700-char block on top of an already-tight prompt.
SUPPLY_PROMPT_MAX_CHARS = 500
# Ceiling on resolved counterparties appended to the candidate list (see
# cascade._identify_companies) -- independent of the line/char caps above,
# which bound the PROMPT TEXT; this bounds how many extra tickers get
# pushed into the tool schema's ticker enum, which is its own token cost
# (see app.companies.candidates' "each candidate costs TWICE" note).
SUPPLY_PROMPT_MAX_EXTRAS = 5
# The evidence gate (app.companies.supply_links.extract._evidence_in_text)
# is this subsystem's entire provenance guarantee -- a supplier/customer
# name is only ever stored because the model quoted text that provably
# appears in the source document. A 1-character (or whitespace-only)
# "quote" trivially substring-matches almost anything and proves nothing,
# so it must be rejected exactly like an unprovable one.
SUPPLY_LINK_MIN_EVIDENCE_CHARS = 40
# A rate-limited/quota-exhausted LLM provider will not un-limit within the
# same drain tick -- without a breaker, a drained-quota day burns TWO calls
# (primary + fallback model) against the provider's requests-per-day limit
# for EVERY remaining pending doc, which also eats the analysis pipeline's
# own fallback-model bucket. Both app.scheduler._run_supply_links_refresh
# and backfill_supply_links.py's drain_extraction_queue stop the drain loop
# after this many CONSECUTIVE llm_failed docs; a successful extraction
# resets the counter.
SUPPLY_LLM_FAILURE_BREAKER = 5

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
# Share counts change only on corporate actions (splits/buybacks/QIPs) --
# refresh far less often than caps.
SHARES_OUTSTANDING_MAX_AGE_DAYS = 180
# A live tick older than this is treated as "market closed" and the
# Directory's live cap falls back to the stored market_cap. Generous
# enough to ride out brief hub reconnects, tight enough that yesterday's
# last tick never masquerades as live today.
LIVE_CAP_TICK_MAX_AGE_MINUTES = 15
# Per-run ceiling on the daily full-universe shares-outstanding sweep --
# ~2,600 Indian companies cover in ~9 runs, then it's maintenance only.
SHARES_SWEEP_BATCH_SIZE = 300

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

# --- Impact-graph v3 (spec 2026-08-11) -----------------------------------
# Distance-aware pruning thresholds: the farther an effect sits from the
# event, the stronger its evidence must be, or the graph becomes an
# "everything affects everything" network. Calibration starting points
# (spec doc 1 §10), not final truths -- telemetry exists so they can be
# re-tuned against labelled events. Applied deterministically in code
# (engine._passes_thresholds), never by the LLM.
IMPACT_DISTANCE_THRESHOLDS: dict[int, dict[str, float]] = {
    1: {"materiality": 0.30, "confidence": 0.55},
    2: {"materiality": 0.35, "confidence": 0.60},
    3: {"materiality": 0.45, "confidence": 0.65},
    4: {"materiality": 0.55, "confidence": 0.70},
    5: {"materiality": 0.60, "confidence": 0.75},
}


def impact_thresholds_for_distance(distance: int) -> dict[str, float]:
    """FINAL-prune thresholds for a causal distance; distances past the
    table reuse the deepest row (they are already capped by
    max_causal_depth). Applied AFTER completeness expansion (architecture
    upgrade 2026-08-12) -- discovery uses the looser floors below."""
    if distance < 1:
        distance = 1
    return IMPACT_DISTANCE_THRESHOLDS.get(distance, IMPACT_DISTANCE_THRESHOLDS[5])


# Discovery-time floors (architecture upgrade 2026-08-12: DISCOVER BROADLY
# FIRST -> AUDIT -> THEN PRUNE). During graph construction an edge only has
# to clear these -- structural checks (types, dedup, cycles) plus a floor
# that rejects the clearly nonsensical. The distance-scaled table above is
# applied once, deterministically, after the completeness audit has had its
# chance to re-open missing branches. Uncertain materiality alone must
# never kill a branch at discovery time.
IMPACT_DISCOVERY_MIN_MATERIALITY = float(os.environ.get("IMPACT_DISCOVERY_MIN_MATERIALITY", "0.15"))
IMPACT_DISCOVERY_MIN_CONFIDENCE = float(os.environ.get("IMPACT_DISCOVERY_MIN_CONFIDENCE", "0.35"))

# Company-mapping call cap per article: exposure-based candidate pools let
# economic nodes (not just sector nodes) map companies, so the number of
# eligible nodes grew -- this bounds the per-article call count the same
# way MAX_EXPANSIONS_PER_ARTICLE bounds ripple discovery.
IMPACT_MAX_COMPANY_MAP_CALLS = int(os.environ.get("IMPACT_MAX_COMPANY_MAP_CALLS", "12"))


# Graph node/edge type vocabularies (spec docs 3 §14). Parent may be any
# of these; a child is never the event itself.
IMPACT_PARENT_TYPES = frozenset({"event", "economic_node", "sector", "commodity", "policy", "company"})
IMPACT_CHILD_TYPES = frozenset({"economic_node", "sector", "commodity", "policy", "company"})

# Gemini thinking budgets per level (tokens). Measured 2026-08-11: dynamic
# "high" thinking (-1) let ONE wide event burn 69k output tokens (~$1-1.6)
# on gemini-3.1-pro-preview -- thinking bills as output, and the model
# spends freely when unbounded. "high" is therefore a FIXED cap. Default
# dropped 3072 -> 1024 (cost-target work, same day): thinking measured as
# ~40-50% of output spend and the 3072 runs showed no visible quality
# edge over the capped ones. Override via GEMINI_THINKING_HIGH_BUDGET.
GEMINI_THINKING_BUDGETS = {
    "minimal": 0, "low": 256, "medium": 512,
    "high": int(os.environ.get("GEMINI_THINKING_HIGH_BUDGET", "1024")),
}

# --- Event-size triage (cost-target work, 2026-08-11) --------------------
# Deterministic, ZERO-cost triage: the facts stage already classifies
# event_type; broad macro types get the deep graph, everything else (most
# pulse items -- single-company earnings, deals, product news) gets a
# small one. Same set the legacy cascade used for fan-out gating.
IMPACT_BROAD_EVENT_TYPES = frozenset(
    s.strip() for s in os.environ.get(
        "IMPACT_BROAD_EVENT_TYPES",
        "repo_rate_change,inflation,macro_data,fiscal_policy,monsoon_weather,"
        "crude_oil,commodity_price,currency_move,global_rates,trade_policy,"
        "geopolitical_conflict",
    ).split(",") if s.strip()
)

# Per-tier engine caps. Token ceilings are the ENFORCED cost mechanism
# (exact, no pricing-table dependence): at ~$12/M Pro output, 5k output
# tokens ~= Rs 5 for a narrow article; broad events get the full budget
# the quality spec demands (their ceiling is the global per-article one).
IMPACT_TRIAGE_TIERS = {
    "narrow": {
        "max_depth": int(os.environ.get("IMPACT_NARROW_MAX_DEPTH", "2")),
        "max_expansions": int(os.environ.get("IMPACT_NARROW_MAX_EXPANSIONS", "4")),
        "max_output_tokens": int(os.environ.get("IMPACT_NARROW_MAX_OUTPUT_TOKENS", "6000")),
        "max_input_tokens": int(os.environ.get("IMPACT_NARROW_MAX_INPUT_TOKENS", "40000")),
        # Narrow articles keep the in-call channel-audit scaffold as their
        # coverage mechanism; a staged completeness loop would break the
        # Rs-5 cost target. 0 by default, env-tunable.
        "completeness_rounds": int(os.environ.get("IMPACT_NARROW_COMPLETENESS_ROUNDS", "0")),
    },
    "broad": {
        "max_depth": None,          # settings.max_causal_depth
        "max_expansions": None,     # engine default
        "max_output_tokens": None,  # settings.gemini_max_output_tokens_per_article
        "max_input_tokens": None,
        # Completeness audit rounds (architecture upgrade 2026-08-12):
        # after discovery + company mapping, an auditor searches for
        # missing branches; found branches re-enter the frontier. Loop
        # stops early when a round adds nothing material.
        "completeness_rounds": int(os.environ.get("IMPACT_BROAD_COMPLETENESS_ROUNDS", "2")),
    },
}
