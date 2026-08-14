from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event, text
from sqlalchemy.orm import relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    ticker = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    sector = Column(String, nullable=False)
    # One of app.companies.sub_sectors.SUB_SECTOR_TAXONOMY[sector], or NULL
    # until backend/backfill_subsectors.py classifies it. See that module for
    # the closed vocabulary and the one-time enrichment job.
    sub_sector = Column(String, nullable=True)
    index_tier = Column(String, nullable=False)  # NIFTY50 | NIFTY100 | NIFTY500 | OTHER
    market_cap = Column(Float, nullable=True)
    isin = Column(String, nullable=True, unique=True)
    instrument_token = Column(Integer, nullable=True)  # Zerodha Kite instrument ID; null until matched
    # Plain-language "what they do" for the (i) button, plus supply-chain
    # suppliers/customers (spec §3.1) -- one-time LLM enrichment, see
    # backend/backfill_business_profiles.py. NULL until enriched.
    business_desc = Column(Text, nullable=True)
    # Provenance for business_desc. NULL source_url means the text is the
    # legacy unattributable LLM value, which every serializer withholds --
    # see app.companies.descriptions. Only a description that can be traced
    # to a named article is ever shown.
    business_desc_source_url = Column(String, nullable=True)
    business_desc_as_of = Column(Date, nullable=True)
    supply_chain_suppliers_json = Column(Text, nullable=True)  # JSON-encoded list[str]
    supply_chain_customers_json = Column(Text, nullable=True)  # JSON-encoded list[str]

    # --- Universe/provenance (docs/superpowers/specs/2026-08-03-stock-
    # universe-cap-tiers-design.md §5.1). market='GLOBAL' rows are the
    # curated non-Indian list in app.companies.global_seed: they have no
    # ISIN, no listings, and never receive a cap tier.
    market = Column(String, nullable=False, default="INDIA", server_default="INDIA")
    # BSE's official 4-level classification, stored verbatim as sourced
    # truth. Company.sector is DERIVED from official_sector via
    # app.companies.universe.sector_map -- never keyword-guessed.
    official_sector = Column(String, nullable=True)
    official_industry = Column(String, nullable=True)
    official_igroup = Column(String, nullable=True)
    official_isubgroup = Column(String, nullable=True)
    classification_source = Column(String, nullable=True)
    classification_as_of = Column(Date, nullable=True)
    market_cap_source = Column(String, nullable=True)  # 'BSE' | 'yfinance'
    market_cap_as_of = Column(Date, nullable=True)
    # Share count for the Directory's live intraday cap (live LTP x shares).
    # Changes only on corporate actions, so it refreshes on a slow sweep
    # (app.companies.market_caps.backfill_shares_outstanding). NULL means
    # "no live cap for this company" -- the stored market_cap is used
    # instead, never a fabricated number.
    shares_outstanding = Column(Float, nullable=True)
    shares_outstanding_as_of = Column(Date, nullable=True)
    # AMFI's PUBLISHED categorisation, when the list is available. Distinct
    # from the derived tier in app.market.cap_tier, which is computed on
    # read and never stored. NULL is normal and expected.
    amfi_tier = Column(String, nullable=True)  # LARGE | MID | SMALL
    amfi_rank = Column(Integer, nullable=True)
    amfi_as_of = Column(Date, nullable=True)
    tradeability = Column(
        String, nullable=False, default="NORMAL", server_default="NORMAL",
    )  # NORMAL | RESTRICTED | SME | SUSPENDED

    # BSE-published fundamentals, from the same ComHeadernew payload the
    # classification comes from -- already fetched monthly, previously
    # discarded. NULL means BSE did not publish it, never zero: a displayed
    # 0.00 ROE reads as a real and alarming number. ConPB and ConROE come back
    # None even for Reliance, so consolidated coverage is genuinely patchy.
    eps = Column(Float, nullable=True)
    ceps = Column(Float, nullable=True)
    pe = Column(Float, nullable=True)
    pb = Column(Float, nullable=True)
    opm = Column(Float, nullable=True)
    npm = Column(Float, nullable=True)
    roe = Column(Float, nullable=True)
    con_eps = Column(Float, nullable=True)
    con_ceps = Column(Float, nullable=True)
    con_pe = Column(Float, nullable=True)
    con_pb = Column(Float, nullable=True)
    con_opm = Column(Float, nullable=True)
    con_npm = Column(Float, nullable=True)
    con_roe = Column(Float, nullable=True)
    financials_source = Column(String, nullable=True)   # 'BSE'
    # PE and PB are price-derived and this payload refreshes monthly, so this
    # date is what keeps them honest -- see spec 5.1.
    financials_as_of = Column(Date, nullable=True)

    listings = relationship("Listing", back_populates="company")
    aliases = relationship("CompanyAlias", back_populates="company")


class CompanyIndexMembership(Base):
    __tablename__ = "company_index_memberships"
    __table_args__ = (UniqueConstraint("company_id", "index_code", name="uq_company_index"),)

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    index_code = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    company = relationship("Company")


class Listing(Base):
    """One row per company per exchange. A dual-listed company (2,278 of
    them as of 2026-08-03) is ONE Company with TWO Listings -- flattening
    this into the company row would force a lie, because a company can be
    series EQ on NSE and group Z on BSE simultaneously."""
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("exchange", "symbol", name="uq_listing_exchange_symbol"),
        UniqueConstraint("company_id", "exchange", name="uq_listing_company_exchange"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    exchange = Column(String, nullable=False)  # NSE | BSE
    symbol = Column(String, nullable=False)  # NSE SYMBOL or BSE scrip_id
    scrip_code = Column(String, nullable=True)  # BSE numeric code; NULL for NSE
    series = Column(String, nullable=True)  # NSE EQ/BE/BZ; NULL for BSE
    group_code = Column(String, nullable=True)  # BSE A/B/T/X/XT/Z/M/MT/MS/P/ZP; NULL for NSE
    status = Column(String, nullable=False, default="ACTIVE")  # ACTIVE | SUSPENDED
    is_sme = Column(Boolean, nullable=False, default=False)
    is_primary = Column(Boolean, nullable=False, default=False)
    face_value = Column(Float, nullable=True)
    listed_on = Column(Date, nullable=True)  # NSE only
    source = Column(String, nullable=False)
    as_of = Column(Date, nullable=False)

    company = relationship("Company", back_populates="listings")


class CompanyAlias(Base):
    """Indexed alias set backing app.companies.matching.matcher. Every rung
    of the match ladder is an EXACT lookup on ``normalized`` -- substring
    matching is what produced silent mismatches in the old resolver."""
    __tablename__ = "company_aliases"
    __table_args__ = (
        UniqueConstraint("normalized", "company_id", name="uq_alias_normalized_company"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    alias = Column(String, nullable=False)
    alias_type = Column(String, nullable=False)  # LEGAL|SHORT|NSE_SYMBOL|BSE_ID|TRADE_NAME
    normalized = Column(String, nullable=False, index=True)

    company = relationship("Company", back_populates="aliases")


class SupplyLink(Base):
    """One sourced counterparty relationship per row (docs/superpowers/
    specs/2026-08-06-supply-links-rating-rationales-design.md §5.1),
    extracted from a rating agency's public rationale document. `evidence`
    is the verbatim quote that survived the extraction gate -- a row
    without a provable quote is never written. counterparty_company_id is
    resolved via the EXACT matching ladder only; NULL means "no exact
    match", never "guessed". These rows feed pipeline prompts as grounding;
    they NEVER create AlertCompany/ImpactEdge rows themselves (user-locked
    constraint, tested by name in tests/test_supply_links.py).
    """
    __tablename__ = "supply_links"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "relation", "counterparty_name",
            name="uq_supply_link_company_relation_counterparty",
        ),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    relation = Column(String, nullable=False)  # SUPPLIER | CUSTOMER
    counterparty_name = Column(String, nullable=False)
    counterparty_company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    evidence = Column(Text, nullable=False)
    source_url = Column(String, nullable=False)
    source_agency = Column(String, nullable=False)
    as_of = Column(Date, nullable=False)
    extracted_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class AnalysisCache(Base):
    """Determinism cache: the same article content (title + body) always
    produces the same analyze_article() output. Keyed by a content hash,
    not article id, so a republished/duplicate article with identical text
    hits the same cache row. See app.pipeline.get_cached_analysis."""
    __tablename__ = "analysis_cache"
    __table_args__ = (UniqueConstraint("content_hash", name="uq_analysis_cache_content_hash"),)

    id = Column(Integer, primary_key=True)
    content_hash = Column(String, nullable=False)
    output_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("url", name="uq_articles_url"),
        # Dedup-path indexes for the collector's per-item idempotency
        # lookups. create_all builds these on a fresh DB; db.py's
        # _ensure_indexes covers DBs whose columns came from the
        # index-less _ADDED_COLUMNS ALTER TABLE path.
        Index("ix_articles_url_hash", "url_hash"),
        Index("ix_articles_provider_article_id", "provider", "provider_article_id"),
    )

    id = Column(Integer, primary_key=True)
    source = Column(String, nullable=False)
    url = Column(String, nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False, default="")
    published_at = Column(DateTime(timezone=True), nullable=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    status = Column(String, nullable=False, default="NEW")  # NEW|FILTERED|CATEGORIZED|ANALYZED|ANALYSIS_FAILED
    category = Column(String, nullable=True)
    image_url = Column(String, nullable=True)  # og:image / twitter:image scraped from the article page
    full_content = Column(Text, nullable=True)  # scraped+extracted full body text, see app/ingestion/full_text.py
    full_content_fetch_attempted_at = Column(DateTime(timezone=True), nullable=True)
    # Multi-source ingestion metadata (app/ingestion/collector.py). All
    # nullable: rows inserted before the provider layer shipped simply have
    # provider=NULL, and nothing downstream reads these -- `source` keeps its
    # existing publisher-display-name meaning untouched.
    provider = Column(String, nullable=True)             # registry slug, e.g. "marketaux"
    provider_article_id = Column(String, nullable=True)  # provider's native id (Marketaux uuid, Benzinga id, BSE NEWSID)
    url_hash = Column(String, nullable=True)             # sha256 of the canonicalized url (tracking params stripped)
    raw_payload = Column(Text, nullable=True)            # original provider item as JSON, for debugging/reprocessing
    source_category = Column(String, nullable=True)      # structured announcement category (NSE/BSE), feeds exchange_noise

    alerts = relationship("Alert", back_populates="article")


class GeminiPaidUsage(Base):
    """One row per article whose analysis was allowed to use the PAID
    Gemini key (app/pipeline.py.select_analysis_client). The unique
    article_id makes budget accounting retry-proof: re-analyzing the same
    article reuses its row instead of consuming budget twice. Today's row
    count IS the spent budget -- no counter to drift."""

    __tablename__ = "gemini_paid_usage"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, unique=True)
    used_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class IngestionSource(Base):
    """One row per registered ingestion source: registry config (enabled,
    poll interval), checkpoint cursor, and health/circuit-breaker state, all
    in one place because all three are per-source state written by the same
    poll cycle (app/ingestion/collector.py).

    Rows are seeded on scheduler boot from each provider's code defaults
    (app/ingestion/providers/registry.py); `enabled` seeds from
    settings.ingestion_enabled_sources so a deployment chooses its active
    sources via env without code changes. After first seed the DB row is the
    source of truth -- flipping `enabled` in the DB takes effect on the next
    poll tick, no redeploy."""

    __tablename__ = "ingestion_sources"

    id = Column(Integer, primary_key=True)
    slug = Column(String, nullable=False, unique=True)
    display_name = Column(String, nullable=False)
    enabled = Column(Integer, nullable=False, default=0)  # 0/1, same convention as User.email_alerts_enabled
    poll_interval_minutes = Column(Integer, nullable=False, default=5)
    cursor = Column(Text, nullable=True)  # opaque per-provider checkpoint (see providers/base.py Checkpoint)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_fetched_count = Column(Integer, nullable=True)   # items returned by the provider this poll, pre-dedup
    last_inserted_count = Column(Integer, nullable=True)  # new Article rows actually inserted this poll
    consecutive_failures = Column(Integer, nullable=False, default=0)
    breaker_open_until = Column(DateTime(timezone=True), nullable=True)  # cooldown window, never a permanent disable
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime(timezone=True), nullable=True)
    # Exponential moving average of (fetched_at - published_at) across
    # inserted items -- the source's real-world delivery latency, for the
    # health endpoint. One aggregate per source, not a time series.
    avg_publish_to_fetch_latency_seconds = Column(Float, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    category = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    # Article-level event classification, parallel to `category`. See
    # docs/superpowers/specs/2026-07-15-reasoning-engine-upgrade-design.md.
    event_type = Column(String, nullable=True)
    prompt_version = Column(String, nullable=True)
    knowledge_version = Column(String, nullable=True)
    # LLM-generated, plain-language event summary (spec §5.2) -- populated
    # post-persist by app.analysis.refinement.refine_alert, never by the
    # cascade stages that produce per-company rationale/magnitude.
    summary_short = Column(String, nullable=True)  # <= 12 words, the one-line "why"
    summary_long = Column(Text, nullable=True)  # 2 sentences, plain language
    # Rumor/denial classification (spec v2 §4.3): 1 when the event is an
    # unconfirmed report / rumor / has been denied -> verdict UNCONFIRMED.
    # Integer 0/1 (same convention as User.email_alerts_enabled), populated
    # by the same refinement LLM call as summary_short; NULL for alerts
    # refined before this shipped (treated as confirmed).
    is_unconfirmed = Column(Integer, nullable=True)
    # The stage-1 distilled article (app.analysis.cascade._extract_facts's
    # `facts` string) this alert's whole cascade reasoned from. Persisted so
    # the refinement layer reasons from the SAME evidence base as the
    # cascade rather than re-reading the raw article -- and so a refinement
    # re-run (or the deferred refinement pass) has that evidence available
    # long after the analysis call. NULL for alerts persisted before this
    # shipped; app.analysis.refinement.refine_alert falls back to the
    # article text in that case.
    facts = Column(Text, nullable=True)
    # --- Fact provenance + event geography (2026-08-14, migration 0009).
    # `facts` above is the PROSE record; these are the structured twins the
    # stage-1 extractor now also produces.
    #
    # fact_items_json: JSON list of {fact_id, text, fact_class}, the classed
    # fact store this alert's whole graph reasoned from (fact_class is one of
    # app.analysis.impact_graph.schemas.FACT_CLASSES). Audit only -- nothing
    # reads it back into reasoning, and the publication gate never sees it.
    # NULL, never "[]", when the run produced no classed facts: an alert
    # analysed before this shipped, or replayed from an older cache entry,
    # genuinely has no record, and an empty array would claim otherwise.
    fact_items_json = Column(Text, nullable=True)
    # Where the event happened. Scope is a GEOGRAPHY_SCOPES value; regions
    # are a JSON list of the article's OWN wording. Both NULL on legacy rows
    # and whenever the article stated nothing -- "UNKNOWN" is never written
    # as a substitute for "not recorded".
    event_geography_scope = Column(String, nullable=True)
    event_geography_regions_json = Column(Text, nullable=True)
    # Deferred-refinement bookkeeping (docs: cost-optimization phase 5).
    # NULL means this alert was refined inline as part of its own analysis
    # run -- the historical behavior and still the default. "pending" means
    # the alert was persisted without its refinement fields and a later
    # batch pass owes them; "done" and "failed" are that pass's outcomes.
    # Every consumer already tolerates the null refinement fields a pending
    # alert has (see app/routers/alerts.py and app/translation/job.py), so
    # a pending alert renders exactly like one whose refinement call
    # returned nothing.
    refinement_status = Column(String, nullable=True)
    refinement_attempts = Column(Integer, nullable=False, default=0)
    # --- Impact-graph v3 provenance (spec 2026-08-11 §14): which provider
    # produced the AUTHORITATIVE graph and at what quality. A Groq (or
    # degraded-Gemini) result must never masquerade as the premium
    # analysis -- these are the visible marks the spec requires.
    # provider: claude on every current run (provider-migration 2026-08-14 --
    # analysis is Claude-only and the router fails closed without a key);
    # gemini | groq survive only as values already written on historical
    # rows. quality: authoritative | degraded | fallback | budget_exhausted.
    # NULL on pre-v3 alerts.
    analysis_provider = Column(String, nullable=True)
    analysis_quality = Column(String, nullable=True)
    # Structured event causation (corrective-v4 task 10): the article's own
    # ROOT CAUSE classification (see app.analysis.impact_graph.schemas.
    # EVENT_CAUSES), distinct from `category`/`event_type` above and from
    # any company's economic_effect. NULL on pre-task-10 rows; "unknown" on
    # rows persisted after this shipped where the model could not classify.
    event_cause = Column(String, nullable=True)
    # --- Idempotency key (final blueprint §26, migration 0008). The stable
    # identity of ONE analysis of ONE article -- the run's own cache key
    # (app.analysis.impact_graph.router's `_v3_cache_key`). Two processes
    # analysing the same article concurrently (the scheduler is explicitly
    # NOT to be relied on as the only serialisation) produce the same key,
    # so the second INSERT collides on uq_alerts_article_content below and
    # is caught by the caller as idempotent success instead of doubling the
    # alert. NULL on the whole legacy corpus and on any path that does not
    # claim an identity -- hence the PARTIAL index.
    content_key = Column(String, nullable=True)

    __table_args__ = (
        # Partial on purpose: a plain unique index would forbid the legacy
        # corpus's many NULL-key alerts per article, and re-analysis with a
        # genuinely different key is not a duplicate.
        Index(
            "uq_alerts_article_content", "article_id", "content_key",
            unique=True,
            sqlite_where=text("content_key IS NOT NULL"),
            postgresql_where=text("content_key IS NOT NULL"),
        ),
    )

    article = relationship("Article", back_populates="alerts")
    companies = relationship("AlertCompany", back_populates="alert")
    impact_edges = relationship("ImpactEdge", order_by="ImpactEdge.id", back_populates="alert")
    cascade_gaps = relationship("CascadeGap", order_by="CascadeGap.id", back_populates="alert")


class AlertCompany(Base):
    __tablename__ = "alert_companies"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    direction = Column(String, nullable=False)  # bullish | bearish
    magnitude_low = Column(Float, nullable=False)
    magnitude_high = Column(Float, nullable=False)
    # Nullable since the precision work: a sector_inference row persists no
    # rationale at all (app.companies.resolution._to_resolved), and a row
    # whose direction was flipped by measurement has its now-contradictory
    # rationale cleared (app.pipeline._persist_alert). Both are "show
    # nothing rather than something misleading", not missing data.
    rationale = Column(Text, nullable=True)
    key_points_json = Column(Text, nullable=True)  # JSON-encoded list[str]; null for pre-existing rows
    confidence_score = Column(Integer, nullable=False, default=50)
    time_horizon = Column(String, nullable=False, default="Short-Term")
    basis = Column(String, nullable=False)  # direct_mention | sector_inference
    confidence = Column(String, nullable=False, default="llm_estimate")  # llm_estimate | calibrated
    # Evidence-discipline + Confidence Engine fields, all JSON-encoded
    # list[str] in *_json columns (same pattern as key_points_json), null for
    # rows created before this feature shipped.
    reasons_json = Column(Text, nullable=True)
    evidence_refs_json = Column(Text, nullable=True)
    risks_json = Column(Text, nullable=True)
    assumptions_json = Column(Text, nullable=True)
    unknowns_json = Column(Text, nullable=True)
    alternative_hypothesis = Column(Text, nullable=True)
    confidence_band = Column(String, nullable=True)  # LOW | MODERATE | HIGH | VERY_HIGH
    confidence_contributors_json = Column(Text, nullable=True)
    confidence_penalties_json = Column(Text, nullable=True)
    # Subset of evidence_refs_json that are real, known rulebook rule ids
    # (app.reasoning.rulebook.get_rule(ref) is not None) -- stored separately
    # for easy future querying of which rules are well-calibrated.
    rulebook_ids_json = Column(Text, nullable=True)
    # Financial grounding + contradiction detection (see docs/superpowers/
    # specs/2026-07-16-financial-grounding-contradiction-detection-design.md).
    # Null for rows persisted before this feature shipped, or when the
    # underlying yfinance fetch failed for this company.
    price_at_analysis = Column(Float, nullable=True)
    return_1m = Column(Float, nullable=True)
    return_3m = Column(Float, nullable=True)
    contradiction_note = Column(Text, nullable=True)
    # How far removed this company's impact is from the article's direct
    # subject -- see app.analysis.schemas.IMPACT_LEVELS. "direct" for both
    # actually-direct mentions and sector-inference fan-out (both are the
    # article's own primary impact). indirect_l1/indirect_l2 are LLM-known
    # supplier/customer/competitor relationships chained off an already-
    # resolved company -- see parent_company_id.
    impact_level = Column(String, nullable=False, default="direct")
    # For impact_level in (indirect_l1, indirect_l2): the Company this one is
    # economically linked through (a direct company for indirect_l1, an
    # indirect_l1 company for indirect_l2). NULL for impact_level="direct".
    parent_company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    # The causal link written AGAINST the already-measured excess_move_pct
    # (see app.market.measure.MarketMove) -- never a prediction. Populated
    # only for companies with measurement_status == "ok"; NULL for a
    # ripple company with no real measured move (never fabricated).
    why = Column(Text, nullable=True)
    # --- Impact-graph v3 (spec 2026-08-11). impact_level above stays the
    # UI-facing legacy label, now DERIVED from causal_distance
    # (1→direct, 2→indirect_l1, 3→indirect_l2, 4+→indirect_l3plus); the
    # graph's own truth is the integer distance. All NULL on pre-v3 rows.
    causal_distance = Column(Integer, nullable=True)
    impact_strength = Column(Float, nullable=True)  # [0,1] size of the possible effect
    confidence_f = Column(Float, nullable=True)     # [0,1] mechanism/exposure certainty
    materiality = Column(Float, nullable=True)      # [0,1] worth showing at all
    # The causal parent this company inherits impact from -- any node type,
    # not only a company (that restriction was v2's parent_ticker model).
    causal_parent_type = Column(String, nullable=True)  # config.IMPACT_PARENT_TYPES
    causal_parent_id = Column(String, nullable=True)    # node id/label, e.g. "crude_oil_price"
    # One-line economic mechanism connecting parent -> this company.
    mechanism = Column(Text, nullable=True)
    # Net-effect reasoning (token-opt spec P12): JSON dict with
    # positive_channels/negative_channels/net_direction/
    # relative_beneficiary. NULL on pre-optimization rows.
    channels_json = Column(Text, nullable=True)
    # Fundamental economic effect (corrective plan task 2, 2026-08-13):
    # positive | negative | mixed | uncertain | no_material_impact. The
    # canonical 5-way DISTINCT truth ("neutral" is a legacy alias, never
    # stored here); `direction` above stays the market-facing legacy view
    # derived from it. NULL on pre-upgrade rows.
    economic_effect = Column(String, nullable=True)
    # V4 strict publication gate (spec §5): the tier the gate authorized
    # ("primary" | "secondary_ripple" | "macro_context"). Ruling R3 /
    # migration 0008: "secondary_deep_dive" (V4) and "secondary"
    # (pre-Task-4) were the SAME tier under two dead names and have been
    # REWRITTEN to "secondary_ripple" in the data. Both dead names are
    # WRITTEN NOWHERE, but they are still READ as legacy-compat -- a DB
    # restored from a pre-0008 backup, or a row written by a binary that
    # predates the rewrite, can still carry them. The readers:
    #   * publication_gate.LEGACY_SECONDARY_SPELLINGS, consumed by
    #     is_secondary_tier / is_displayable_tier -- THE canonical place
    #     the legacy spellings are accepted; market/ripple_layers and
    #     analysis/impact_graph/consistency read them only through it,
    #     holding no tier tuple of their own,
    #   * routers/feed_v2._SECONDARY_TIERS (a local tuple, pending its
    #     swap to the gate helper),
    #   * tools/offline_benchmark.DEEP_DIVE_TIERS (same, in the benchmark
    #     harness).
    # Plus the terminal gate state. NULL on rows
    # persisted with the flag off -- legacy rows have no gate semantics,
    # and consumers must treat NULL as legacy, never as eligible.
    display_tier = Column(String, nullable=True)
    gate_state = Column(String, nullable=True)
    # The COMPOSITE materiality grade the gate actually evaluated (final-
    # review finding I3, migration 0007): app.analysis.impact_graph.
    # materiality.materiality_grade's output -- the LLM's raw float capped
    # by the company's own exposure ordinal and the evidence tier -- i.e.
    # the exact value that rode on CandidateInput.materiality_grade. Stored
    # because it CANNOT be recovered from `materiality` alone: re-deriving
    # a grade from the naked float (what app.market.ripple_layers did) can
    # serve HIGH for a candidate the gate capped to MEDIUM. NULL on legacy
    # and ungated rows -- there is no composite grade for those, and one
    # must never be invented.
    materiality_grade = Column(String, nullable=True)
    # Expected market sensitivity (corrective-v4 task 10): HIGH/MEDIUM/LOW/
    # UNKNOWN, set ONLY from GraphCompany.expected_market_sensitivity (the
    # model's own judgment at mapping time) -- never derived from
    # price_at_analysis/return_1m/return_3m above, which belong to the
    # separately-measured market-reaction layer. NULL on pre-task-10 rows.
    expected_market_sensitivity = Column(String, nullable=True)
    # --- Final blueprint §21/§22 (migration 0008). `basis` used to carry
    # three different questions at once ("direct_mention" answered how the
    # candidate was FOUND, how CAUSALLY CLOSE it is, and what kind of
    # evidence backs it). Each now has its own column with its own closed
    # vocabulary, and none is derivable from another -- §11 is explicit
    # that DIRECT/INDIRECT cannot be read off causal_distance (crude ->
    # IndiGo ATF is DIRECT at d1; crude -> INR -> IT exporter is INDIRECT
    # at the same or greater distance). All NULL on pre-blueprint rows;
    # `basis` stays for legacy compatibility and is never the current
    # truth.
    causal_directness = Column(String, nullable=True)   # DIRECT | INDIRECT | REMOTE
    # ARTICLE_MENTION | MECHANISM_MAPPING | EXPOSURE_RULE | RIPPLE_DISCOVERY
    # | ESCALATION | COMPLETENESS | CURATED
    discovery_source = Column(String, nullable=True)
    # PRIMARY | STRUCTURED | VERIFIED | CURATED | MODEL | MARKET_OBSERVATION
    # -- the KIND of evidence, distinct from `evidence_class`'s A/B/C/D tier.
    evidence_source = Column(String, nullable=True)
    # The §21 controlled relationship type for THIS company's own edge
    # (REVENUE_REALIZATION | INPUT_COST | OPERATING_MARGIN | REFINING_SPREAD
    # | MARKETING_MARGIN | DEMAND | PRICING_POWER | CURRENCY_TRANSLATION |
    # VALUATION_MULTIPLE | CAPEX | SUPPLY | COMPETITIVE | REGULATORY |
    # FINANCING | OTHER). The real graph labelled upstream realization,
    # aviation fuel cost and refining margin all as "demand"; the relation
    # must match the actual economic mechanism.
    edge_relation = Column(String, nullable=True)

    __table_args__ = (
        # Corrective-v4 Task 18 (plan-gap carry): a bug anywhere upstream
        # that calls _build_alert_company twice for the same candidate used
        # to silently double a company's card on the feed -- migration 0006
        # pre-dedupes any legacy violation (keeping MAX(id)) before adding
        # this constraint.
        UniqueConstraint("alert_id", "company_id", name="uq_alert_company_alert_company"),
    )

    alert = relationship("Alert", back_populates="companies")
    company = relationship("Company", foreign_keys=[company_id])
    parent_company = relationship("Company", foreign_keys=[parent_company_id])


# ---------------------------------------------------------------------------
# Gated-row consistency backstop (final blueprint §26, migration 0008)
# ---------------------------------------------------------------------------
# The real run exposed a STALE PRE-V4 WORKER mutating a gated row after the
# publication gate had authorized it: `economic_effect` said positive, and
# something outside the V4 code path wrote a bearish `direction` over the
# top. Application-side guards (app/pipeline.py's `gate_state is not None`
# skips in measure_and_reconcile_alert_companies and the remeasure pass)
# only protect the binaries that carry them -- a stale container, an old
# worker class, a one-off script all still hold a write handle to the same
# database file. §26 therefore requires enforcement at the DB, so the guard
# fires inside ANY binary that touches the row.
#
# NARROW ON PURPOSE. The triggers refuse exactly three end states, and only
# on a GATED row (gate_state IS NOT NULL):
#   * positive economic_effect left with a bearish direction,
#   * negative economic_effect left with a bullish direction
#     (§4: `economic_effect` is the ONE authoritative field and `direction`
#     is derived from it -- mixed/uncertain/no_material_impact map to
#     "neutral" and are deliberately NOT constrained here),
#   * (UPDATE only) a rationale that HAD text being nulled -- the stale
#     worker's other signature move, clearing the reasoning of a row whose
#     direction it had just flipped.
# Legacy rows (gate_state IS NULL) have no gate semantics to protect and
# keep byte-identical pre-gate behaviour: the backstop must not
# retroactively freeze the pre-V4 corpus.
#
# WHY A DDL HOOK AND NOT ONLY THE MIGRATION. Production DBs get these from
# migration 0008; every create_all-built DB (the whole test suite's
# in-memory fixture, tools/migrate_on_boot.py's _create_missing_tables, a
# fresh dev DB) would otherwise carry the schema WITHOUT the backstop, so
# the guarantee would hold in production and silently not hold anywhere it
# is tested. The SQL below is duplicated verbatim in
# alembic/versions/0008_three_tier_blueprint.py on purpose: a migration
# must never import app code, which drifts underneath it. If you change one,
# change both -- and tests/test_migrations.py's
# test_models_and_0008_trigger_ddl_are_byte_identical reads 0008's SOURCE
# and compares the normalized SQL, so drift fails the suite rather than
# silently diverging migrated DBs from create_all-built ones.
#
# ###################################################################
# ## WARNING TO ANY 0009+ MIGRATION AUTHOR                         ##
# ##                                                               ##
# ## Alembic's `op.batch_alter_table` on SQLite RECREATES the      ##
# ## table (CREATE new -> copy rows -> DROP old -> RENAME), and    ##
# ## SQLite DROPs every trigger attached to a dropped table.       ##
# ## Alembic does NOT copy triggers, and this `after_create` hook  ##
# ## does NOT fire on an Alembic batch rebuild -- so ANY future    ##
# ## migration that batch-alters `alert_companies` (adding a       ##
# ## column, altering a constraint, anything with                  ##
# ## recreate="always" or a SQLite ALTER that Alembic implements   ##
# ## by rebuild) SILENTLY DROPS THIS ENTIRE BACKSTOP.              ##
# ##                                                               ##
# ## Such a migration MUST re-emit the triggers at the END of the  ##
# ## batch operation. Migrations must not import app code, so      ##
# ## copy the two CREATE TRIGGER statements below verbatim into    ##
# ## that migration (the byte-identity test above will keep them   ##
# ## honest), or call `emit_gated_row_triggers(bind)` from any     ##
# ## NON-migration code path that needs them.                      ##
# ###################################################################
#
# SQLite only. Postgres has no `CREATE TRIGGER IF NOT EXISTS` and needs a
# trigger FUNCTION plus a CHECK-style raise; that port is a documented
# follow-up (see the 0008 docstring). Emitting nothing on other dialects is
# correct rather than half-enforcing.
_GATED_CONSISTENCY_UPDATE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS alert_companies_gated_consistency
BEFORE UPDATE ON alert_companies
FOR EACH ROW
WHEN NEW.gate_state IS NOT NULL
 AND (
   (NEW.economic_effect = 'positive' AND NEW.direction = 'bearish')
   OR (NEW.economic_effect = 'negative' AND NEW.direction = 'bullish')
   OR (NEW.rationale IS NULL AND OLD.rationale IS NOT NULL)
 )
BEGIN
  SELECT RAISE(ABORT, 'gated row consistency violation');
END
"""

# Same shape on INSERT so a contradictory gated row can never LAND, only
# never be updated into existence. OLD does not exist in a BEFORE INSERT
# trigger, so the rationale clause is necessarily absent here.
_GATED_CONSISTENCY_INSERT_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS alert_companies_gated_consistency_insert
BEFORE INSERT ON alert_companies
FOR EACH ROW
WHEN NEW.gate_state IS NOT NULL
 AND (
   (NEW.economic_effect = 'positive' AND NEW.direction = 'bearish')
   OR (NEW.economic_effect = 'negative' AND NEW.direction = 'bullish')
 )
BEGIN
  SELECT RAISE(ABORT, 'gated row consistency violation');
END
"""


# The public, reusable form. Both statements in application order, exported
# so any NON-migration code path that rebuilds or adopts an alert_companies
# table can reinstall the backstop instead of re-typing the SQL. (Alembic
# migrations must NOT import this -- see the warning block above; they copy
# the literals and are held byte-identical by test_migrations.py.)
GATED_ROW_TRIGGER_DDL = (
    _GATED_CONSISTENCY_UPDATE_TRIGGER,
    _GATED_CONSISTENCY_INSERT_TRIGGER,
)


def emit_gated_row_triggers(bind) -> bool:
    """Install the §26 gated-row backstop on `bind` (a Connection or
    Engine-like object exposing `.dialect` and `.execute`). Idempotent --
    every statement is CREATE TRIGGER IF NOT EXISTS. Returns True if the
    triggers were emitted, False on a non-SQLite dialect (where they are
    deliberately a no-op pending the Postgres port)."""
    if bind.dialect.name != "sqlite":
        return False
    for statement in GATED_ROW_TRIGGER_DDL:
        bind.execute(text(statement))
    return True


@event.listens_for(AlertCompany.__table__, "after_create")
def _install_gated_consistency_triggers(target, connection, **kw):
    emit_gated_row_triggers(connection)


class CascadeGap(Base):
    """A cascade-company lookup (app.analysis.cascade) that failed even
    after a retry -- recorded instead of silently dropped, so the user can
    always see "this ripple path was considered and could not be
    resolved" rather than a difference between runs that looks like a
    missing feature. See app.analysis.cascade._identify_companies_per_sector."""
    __tablename__ = "cascade_gaps"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    sector = Column(String, nullable=False)
    impact_level = Column(String, nullable=False)
    # The per-sector cascade call chains from a POOL of parent companies,
    # not one -- null here, not misleadingly picking just the first parent.
    # See the comment at the call site in _identify_companies_per_sector.
    parent_ticker = Column(String, nullable=True)
    attempts = Column(Integer, nullable=False)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    alert = relationship("Alert", back_populates="cascade_gaps")


class ImpactEdge(Base):
    """One verified or pruned edge in an alert's transmission-chain graph
    (see app.analysis.cascade._generate_edges). from_company_id/
    to_company_id are set only when the corresponding node is a company AND
    that ticker resolved to a real Company row at persist time -- null
    otherwise (the edge still renders with its label, just without a
    company link). See app.reasoning.rulebook.EDGE_RELATIONS for valid
    `relation` values."""
    __tablename__ = "impact_edges"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    from_company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    from_node_kind = Column(String, nullable=False)  # company | sector | mechanism
    from_label = Column(String, nullable=False)
    to_company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    to_node_kind = Column(String, nullable=False)
    to_label = Column(String, nullable=False)
    relation = Column(String, nullable=False)
    direction = Column(String, nullable=False)  # bullish | bearish
    note = Column(Text, nullable=False)
    source = Column(String, nullable=False)  # rulebook_verified | rulebook_pruned | llm_only
    confidence_score = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    # --- Impact-graph v3 (spec 2026-08-11) -- typed causal edge fields.
    # from_node_kind/to_node_kind above keep carrying the legacy vocabulary
    # for old rows; these carry the graph vocabulary (config.
    # IMPACT_PARENT_TYPES / IMPACT_CHILD_TYPES) for engine-written rows.
    # NULL on every pre-v3 row -- readers must tolerate absence.
    parent_type = Column(String, nullable=True)   # event | economic_node | sector | commodity | policy | company
    child_type = Column(String, nullable=True)    # economic_node | sector | commodity | policy | company
    causal_distance = Column(Integer, nullable=True)  # child's distance from the event
    impact_strength = Column(Float, nullable=True)    # [0,1]
    confidence_f = Column(Float, nullable=True)       # [0,1] -- float twin of confidence_score
    materiality = Column(Float, nullable=True)        # [0,1]
    time_horizon = Column(String, nullable=True)      # Immediate | Short-Term | Medium-Term | Long-Term
    # 5-way fundamental effect (architecture upgrade 2026-08-12 §11);
    # NULL on pre-upgrade rows.
    economic_effect = Column(String, nullable=True)
    verification_status = Column(String, nullable=True)  # verified | pruned | unverified

    __table_args__ = (
        # Corrective-v4 Task 18 (plan-gap carry): the audit report script
        # and the internal decisions endpoint both look up an alert's whole
        # edge set; alert_id carried no index before migration 0006.
        Index("ix_impact_edges_alert_id", "alert_id"),
    )

    alert = relationship("Alert", back_populates="impact_edges")


class LLMStageCache(Base):
    """Durable per-stage LLM result cache (retry-burn fix, 2026-08-11).
    A failed analysis retried later (second attempt, hourly retry sweep,
    post-deploy re-queue) re-runs the SAME stage calls with byte-identical
    inputs -- before this table, every retry re-billed Gemini for stages
    that had already succeeded (measured: the bulk of one day's paid
    spend produced zero feed articles). Keyed by a fingerprint of
    stage + model + full prompt + schema, so any input drift is simply a
    cache miss that pays normally -- correctness never depends on a hit.
    Failures are never cached. Rows expire after STAGE_CACHE_TTL_DAYS."""
    __tablename__ = "llm_stage_cache"

    id = Column(Integer, primary_key=True)
    fingerprint = Column(String, nullable=False, unique=True, index=True)
    stage = Column(String, nullable=False)
    article_id = Column(Integer, nullable=True)
    model = Column(String, nullable=True)
    result_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class CompanyNodeExposure(Base):
    """Stable (company, economic_node) relationship cache (token-opt spec
    P10/P24). Written from VERIFIED impact-graph results only: a company
    the verifier accepted for a normalized node stores a positive row
    (exposure_exists=1, base mechanism); a rejected company stores a
    negative row (exposure_exists=0), which lets future analyses skip
    re-evaluating that dead relationship entirely. Base exposure only --
    the event-specific magnitude/direction is always re-judged by the
    model, which may override a stale row. Invalidated (ignored) when the
    company's metadata is newer than verified_at."""
    __tablename__ = "company_node_exposures"
    __table_args__ = (UniqueConstraint("company_id", "node_key", name="uq_company_node_exposure"),)

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    node_key = Column(String, nullable=False)  # normalized economic-node id
    exposure_exists = Column(Integer, nullable=False)  # 1 positive | 0 negative
    strength = Column(Float, nullable=True)  # last verified impact_strength
    mechanism = Column(Text, nullable=True)  # base-exposure mechanism, one line
    verified_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    source_alert_id = Column(Integer, nullable=True)
    # How this relationship was established (spec 2026-08-12 §8; corrective-
    # v4 Task 6 narrows the vocabulary that matters for evidence): the
    # verifier writes MODEL_VERIFIED -- the SYSTEM's own accepted prior,
    # never independent evidence. Only SUPPLY_LINK / MANUAL / CURATED are
    # independently-sourced provenance a claim may cite as Tier C
    # (app.analysis.impact_graph.evidence.classify_evidence). NULL on rows
    # from before provenance shipped -- classified LEGACY_UNVERIFIED, a
    # candidacy prior only, same as MODEL_VERIFIED.
    provenance_type = Column(String, nullable=True)
    # Independently-sourced provenance detail (Task 6): populated only when
    # provenance_type is SUPPLY_LINK/MANUAL/CURATED. NULL on MODEL_VERIFIED
    # rows -- there is no independent source to cite.
    source_type = Column(String, nullable=True)
    source_url = Column(String, nullable=True)
    source_date = Column(Date, nullable=True)
    evidence_id = Column(Integer, ForeignKey("evidence_records.id"), nullable=True)
    # Prompt/schema version pair active when this row was written (Task 6) --
    # lets a future audit tell which prompt generation produced a given
    # prior without re-deriving it from source_alert_id.
    verification_version = Column(String, nullable=True)
    # Expiry checkpoint for the SELF-CERTIFICATION FIX (Task 6, spec §8/§9):
    # a MODEL_VERIFIED prior compounds forever without one -- a company the
    # verifier accepted once would keep auto-qualifying as "fresh" on every
    # future event indefinitely. exposure_row_is_fresh treats a row past its
    # own review_after as stale, same as metadata staleness. NULL means no
    # checkpoint was set (rows from before this column existed).
    review_after = Column(DateTime(timezone=True), nullable=True)

    company = relationship("Company")


class CompanyDecisionRecord(Base):
    """Durable audit record for every v3 company candidate that reached the
    publication boundary (spec 2026-08-12 §35, INV-019/020). One row per
    (alert, ticker) decision: why the candidate was accepted or rejected,
    which gates it passed, what evidence class carried it. Written only in
    strict mode -- the debugging backbone that lets postmortems answer
    "why was this shown / hidden" without re-running paid analysis."""
    __tablename__ = "company_decision_records"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    ticker = Column(String, nullable=False)
    final_state = Column(String, nullable=False)     # DISPLAY_ELIGIBLE | REJECT_*
    # primary | secondary_ripple | macro_context | excluded. Ruling R3 /
    # migration 0008 rewrote every legacy "secondary_deep_dive" and
    # "secondary" row to "secondary_ripple"; neither dead name is WRITTEN
    # any more, but both are still READ as legacy-compat (see
    # AlertCompany.display_tier above for the readers).
    display_tier = Column(String, nullable=False)
    rejection_reason = Column(String, nullable=True)  # REJECT_* or NULL
    gates_passed_json = Column(Text, nullable=True)   # JSON list of gate names
    evidence_class = Column(String, nullable=True)
    materiality_grade = Column(String, nullable=True)  # HIGH | MEDIUM | LOW | UNKNOWN
    candidate_json = Column(Text, nullable=True)       # gate-input snapshot
    analysis_version = Column(String, nullable=True)   # prompt/schema version pair
    # Decision-record completeness (spec sec54, corrective-v4 Task 18): the
    # full audit trail a postmortem needs without re-running paid analysis.
    # discovery_sources_json: GraphCompany.discovery_source (see
    # app.analysis.impact_graph.engine), JSON list-wrapped for a future
    # multi-source merge; "unknown" is the honest value for a candidate
    # whose discovery path was never stamped.
    discovery_sources_json = Column(Text, nullable=True)
    # Full CandidateInput dataclasses.asdict() (app.analysis.impact_graph.
    # publication_gate) -- the EXACT input the gate walked, not a
    # reconstruction from this row's other columns.
    gate_inputs_json = Column(Text, nullable=True)
    # EvidenceRecord ids this candidate's classification produced --
    # duplicated out of candidate_json.evidence_ids as its own column so a
    # query never has to parse JSON to join to evidence_records.
    evidence_ids_json = Column(Text, nullable=True)
    # Provider-migration 2026-08-14: analysis runs on Claude only (Groq is
    # forbidden for impact analysis and the router fails closed without a
    # Claude key) -- "gemini"/"groq" survive only as values already written
    # on historical rows.
    provider = Column(String, nullable=True)           # claude (legacy: gemini | groq)
    model = Column(String, nullable=True)              # best-effort model name for `provider`
    analysis_quality = Column(String, nullable=True)   # authoritative | fallback | degraded | failed
    # The verifier's raw per-company correction dict (app.analysis.
    # impact_graph.engine._apply_company_correction), NULL when the
    # verifier never corrected this candidate.
    correction_json = Column(Text, nullable=True)
    # Final blueprint §11/§22 (migration 0008): the DIRECT/INDIRECT/REMOTE
    # judgment the gate actually evaluated. Kept as its own column because
    # a postmortem cannot re-derive it -- §11 forbids reading directness
    # off causal_distance. NULL on pre-blueprint records.
    causal_directness = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        # LEDGER RULING (corrective-v4 Task 18, supersedes the plan's
        # UniqueConstraint on alert_id/ticker/analysis_version): a
        # REJECT_DUPLICATE row for the same ticker in the same alert is
        # part of the audit trail, not a data-integrity defect -- a unique
        # constraint here would reject exactly the rows this table exists
        # to keep. A composite index supports lookups without constraining
        # cardinality.
        Index("ix_decision_alert_ticker", "alert_id", "ticker"),
    )

    alert = relationship("Alert")
    company = relationship("Company")


class EvidenceRecord(Base):
    """Structured evidence backing one company's claim within one alert
    (corrective-v4 Task 5, spec §18). Replaces the free-text `evidence_refs`
    an LLM lists on its own claims: those strings are useful DISPLAY hints
    but were never independently checked, so they can never be the thing
    that raises a claim's evidence tier (app.pipeline._build_alert_company
    only counts rulebook-MATCHED refs toward confidence at all -- see
    app.analysis.impact_graph.evidence.classify_evidence for the producer).
    A row here is either a real artifact (a SupplyLink's verbatim
    rating-agency quote) or an explicit non-claim (the article itself
    naming the company as its subject) -- never an invented citation
    (INV-guarded by test_no_evidence_record_is_ever_fabricated).

    `event_id` is the DB column name -- this row belongs to one alert's
    (one event's) analysis of one company; the ORM attribute is `alert_id`
    for consistency with every other model that references alerts.id.
    """
    __tablename__ = "evidence_records"
    __table_args__ = (
        Index("ix_evidence_alert_company", "event_id", "company_id"),
    )

    id = Column(Integer, primary_key=True)
    alert_id = Column("event_id", Integer, ForeignKey("alerts.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    mechanism_id = Column(String, nullable=True)
    evidence_class = Column(String, nullable=False)
    evidence_tier = Column(String, nullable=False)
    source_type = Column(String, nullable=False)
    source_name = Column(String, nullable=False)
    source_url = Column(String, nullable=True)
    source_date = Column(Date, nullable=True)
    as_of_date = Column(Date, nullable=True)
    quoted_text = Column(Text, nullable=True)
    fact_text = Column(Text, nullable=False)
    quality = Column(String, nullable=True)
    reliability = Column(Float, nullable=True)
    provenance_type = Column(String, nullable=True)
    supports_claim = Column(Boolean, nullable=False, default=True)
    supports_direction = Column(Boolean, nullable=True)
    supports_materiality = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    review_after = Column(DateTime(timezone=True), nullable=True)

    alert = relationship("Alert")
    company = relationship("Company")


class CalibrationSample(Base):
    __tablename__ = "calibration_samples"
    __table_args__ = (
        UniqueConstraint("alert_company_id", "horizon_days", name="uq_calibration_alert_company_horizon"),
    )

    id = Column(Integer, primary_key=True)
    alert_company_id = Column(Integer, ForeignKey("alert_companies.id"), nullable=False)
    category = Column(String, nullable=False)  # copied from the Alert's category at sample time
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    direction = Column(String, nullable=False)  # bullish | bearish (sign of magnitude_actual)
    magnitude_actual = Column(Float, nullable=False)  # actual % price move over the horizon
    horizon_days = Column(Integer, nullable=False)  # 1 | 3 | 7
    sampled_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class CarOutcome(Base):
    """Cumulative Abnormal Return outcome (docs/NEWS_IMPACT_APP_SPEC.md
    §4.6) -- one row per (alert, company), written exactly once by
    app.outcomes.car.check_pending_car_outcomes once trading days -1..+3
    around the alert have fully traded. Never updated afterward, same
    immutable-snapshot discipline as MarketMove. day0_excess_move_pct is
    copied from that alert/company's own MarketMove.excess_move_pct at
    sample time (the original flagged reaction); car_pct is the actual
    Sum(ticker return - benchmark return) over the window (app.outcomes.
    price_fetcher.fetch_cumulative_excess_return). category is copied
    from Alert.category at sample time, same reclassification-safety
    reason CalibrationSample already documents for its own category
    column."""
    __tablename__ = "car_outcomes"
    __table_args__ = (UniqueConstraint("alert_company_id", name="uq_car_outcome_alert_company"),)

    id = Column(Integer, primary_key=True)
    alert_company_id = Column(Integer, ForeignKey("alert_companies.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    category = Column(String, nullable=False)
    day0_excess_move_pct = Column(Float, nullable=False)
    car_pct = Column(Float, nullable=False)
    # JSON-encoded list[float]: the per-trading-day excess returns across
    # the -1..+3 window (5 values), so the review screen can draw the
    # day-by-day bar track (spec v2 §4.7 review screen), not just the sum.
    # NULL for rows computed before this column shipped -- the UI falls
    # back to showing car_pct alone, never a fabricated series.
    car_series_json = Column(Text, nullable=True)
    computed_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class EventVolatilityRange(Base):
    """One empirical reaction range per (level, subject, news category) --
    subsystem D (docs/superpowers/specs/2026-08-05-event-volatility-ranges-
    design.md). Built nightly by app.market.event_volatility from measured
    market_moves rows only; fully rebuilt each run (an aggregate has no
    identity worth preserving). No LLM ever writes here.

    level=COMPANY rows set company_id (sector NULL); level=SECTOR rows set
    sector (company_id NULL) and pool every measured company in that
    sector. The unique constraint is belt-and-braces -- the full rebuild
    makes duplicates structurally impossible.
    """
    __tablename__ = "event_volatility_ranges"
    __table_args__ = (
        UniqueConstraint(
            "level", "company_id", "sector", "category",
            name="uq_event_vol_level_subject_category",
        ),
    )

    id = Column(Integer, primary_key=True)
    level = Column(String, nullable=False)  # COMPANY | SECTOR
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    sector = Column(String, nullable=True)
    category = Column(String, nullable=False)
    n_events = Column(Integer, nullable=False)
    min_excess_move_pct = Column(Float, nullable=False)
    median_excess_move_pct = Column(Float, nullable=False)
    max_excess_move_pct = Column(Float, nullable=False)
    as_of = Column(Date, nullable=False)
    source = Column(String, nullable=False, default="market_moves")


class MarketMove(Base):
    """One row per (event, ticker) -- the measured facts backing every
    user-facing number (docs/NEWS_IMPACT_APP_SPEC.md §3.1, §3.2). ``event``
    here is an Alert row (this codebase's NewsEvent). Arithmetic on
    observed prices only -- no LLM ever writes to this table. A row always
    exists once an alert is persisted (one per resolved company), even when
    measurement failed -- measurement_status='no_data' with null metric
    columns records that honestly rather than omitting the row.
    """
    __tablename__ = "market_moves"
    __table_args__ = (UniqueConstraint("alert_id", "company_id", name="uq_market_move_alert_company"),)

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    raw_move_pct = Column(Float, nullable=True)
    sector_move_pct = Column(Float, nullable=True)
    benchmark_ticker = Column(String, nullable=False)
    # Alert.category copied at measurement time. Alerts can be
    # recategorized after the fact; a live join would silently re-shuffle
    # which range pool historical moves belong to. Same reclassification-
    # safety pattern calibration_samples.category documents. NULL on rows
    # that predate this column (backfill_event_volatility.py fills them).
    category = Column(String, nullable=True)
    excess_move_pct = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    avg_volume_20d = Column(Float, nullable=True)
    volume_multiple = Column(Float, nullable=True)
    # Spec v2 §3.1/§4.2 signal inputs, all measured facts (never LLM):
    # delivery_pct -- % of day volume taken to delivery (India edge). NULL
    # until a real NSE delivery-data source is wired in; intensity
    # renormalizes its weight away rather than fabricating (spec Ground
    # Rules: omit rather than invent).
    delivery_pct = Column(Float, nullable=True)
    # vol_normalized -- |raw move| / stdev of the stock's own trailing daily
    # returns (move vs its own volatility, spec §4.2). NULL when history is
    # too short.
    vol_normalized = Column(Float, nullable=True)
    # materiality -- news size vs company size (spec §4.2): excess traded
    # value on the day (over the 20d average, in currency terms) as a
    # fraction of market cap. Deterministic proxy computed from measured
    # bars only. NULL when market cap or volume history is unavailable.
    materiality = Column(Float, nullable=True)
    # avg_traded_value -- 20-day average of close x volume; the liquidity-
    # tier input (spec §4.6). Tier itself is derived on read, never stored.
    avg_traded_value = Column(Float, nullable=True)
    measured_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    measurement_status = Column(String, nullable=False)  # ok | no_data | stale | data_invalid
    # Bar-integrity transparency (spec 2026-08-12 §21): the market date of
    # the bar this measurement read, and whether that bar was a completed
    # session (0 = measured mid-session, a partial intraday snapshot).
    # NULL on rows measured before these shipped.
    last_bar_date = Column(String, nullable=True)  # ISO date
    bar_complete = Column(Integer, nullable=True)  # 1 complete | 0 partial
    # Market-integrity hardening (Task 14, spec §21/§22): data_quality is a
    # finer-grained honesty signal than measurement_status alone --
    # "ok"/"partial_bar"/"stale"/"invalid", or NULL when nothing was
    # measured at all (no_data), a deliberately distinct "nothing to grade"
    # state from any of the four. session_state is the NSE session state
    # (open/closed/holiday, app.market.calendar.session_state) AT
    # MEASUREMENT TIME, not read time. reaction_significance
    # (significant/normal/noise/unknown, app.market.measure.
    # reaction_significance) is a magnitude-worth-flagging judgment,
    # distinct from classify_reaction's sign. All three NULL on rows
    # measured before this column shipped.
    data_quality = Column(String, nullable=True)
    session_state = Column(String, nullable=True)
    reaction_significance = Column(String, nullable=True)

    alert = relationship("Alert")
    company = relationship("Company")


class TimelineEffect(Base):
    """One row per (alert, horizon) -- how the event's effect unfolds over
    time (docs/NEWS_IMPACT_APP_SPEC.md §3.1, §4 Level 3). Only horizons the
    LLM refinement layer found genuine, distinct content for get a row --
    zero, one, or several rows per alert, never a fixed five. Populated by
    app.analysis.refinement.refine_alert, same call as Alert.summary_short/
    summary_long and AlertCompany.why.
    """
    __tablename__ = "timeline_effects"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    horizon = Column(String, nullable=False)  # TODAY | DAYS | WEEKS | MONTHS | QUARTERS
    description = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    alert = relationship("Alert")


class AlertRippleLayer(Base):
    """One story-specific card-back section for an alert (spec v2 §5) --
    generated per alert by the LLM refinement layer, which adapts the
    archetype patterns to THIS story (and invents new section shapes when
    the news doesn't fit an archetype) instead of forcing a fixed
    template onto every event. Zero rows for an alert means refinement
    never produced layers (or predates this feature) -- read time falls
    back to the static archetype template, then to generic relationship
    buckets. tickers_json is a JSON-encoded, validated list of this
    alert's own affected tickers; a ticker no layer claims is appended to
    the fallback buckets at read time -- every company always renders
    exactly once, never dropped, never duplicated."""
    __tablename__ = "alert_ripple_layers"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    position = Column(Integer, nullable=False)
    title = Column(String, nullable=False)  # e.g. "Winners — refiners & marketers"
    # NOTE: the ORM relationship to Alert is declared BEFORE this column --
    # the column is named `relationship` (spec §3.1 RippleLayerDef) and
    # would otherwise shadow sqlalchemy.orm.relationship inside this class
    # body.
    alert = relationship("Alert")
    relationship = Column(String, nullable=False)  # spec §5 standard relationship types
    note = Column(Text, nullable=False)
    tickers_json = Column(Text, nullable=False)  # JSON-encoded list[str]
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class FinancialSnapshot(Base):
    """Cached price/return data for a ticker, refreshed on a TTL by
    app.reasoning.financial_context.get_or_fetch_financial_snapshot -- avoids
    re-hitting yfinance for the same company across multiple alerts in a
    short window."""
    __tablename__ = "financial_snapshots"
    __table_args__ = (UniqueConstraint("ticker", name="uq_financial_snapshot_ticker"),)

    id = Column(Integer, primary_key=True)
    ticker = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    return_1m = Column(Float, nullable=True)
    return_3m = Column(Float, nullable=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False, unique=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    # Integer, not Boolean: production Postgres already has this column as
    # INTEGER (see db.py's _ADDED_COLUMNS) -- matching it here avoids a second
    # schema migration. 1/0, not True/False, at every read/write site.
    email_alerts_enabled = Column(Integer, nullable=False, default=1, server_default="1")


class Holding(Base):
    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_holdings_user_company"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    quantity = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class EmailNotification(Base):
    __tablename__ = "email_notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "alert_company_id", name="uq_notification_user_alert_company"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    alert_company_id = Column(Integer, ForeignKey("alert_companies.id"), nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending | sent | failed
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    sent_at = Column(DateTime(timezone=True), nullable=True)


class UserWatchlistCategory(Base):
    __tablename__ = "user_watchlist_categories"
    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_watchlist_category_user_category"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class UserWatchlistCompany(Base):
    __tablename__ = "user_watchlist_companies"
    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_watchlist_company_user_company"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class ArticleTranslation(Base):
    __tablename__ = "article_translations"
    __table_args__ = (UniqueConstraint("article_id", "lang", name="uq_article_translation_lang"),)

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    lang = Column(String, nullable=False)  # hi | mr | gu | ml | te | ta | kn
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    article = relationship("Article")


class AlertCompanyTranslation(Base):
    __tablename__ = "alert_company_translations"
    __table_args__ = (
        UniqueConstraint("alert_company_id", "lang", name="uq_alert_company_translation_lang"),
    )

    id = Column(Integer, primary_key=True)
    alert_company_id = Column(Integer, ForeignKey("alert_companies.id"), nullable=False)
    lang = Column(String, nullable=False)
    rationale = Column(Text, nullable=False)
    key_points_json = Column(Text, nullable=False, default="[]")
    # Translated AlertCompany.why (the spec-v2 card back's causal one-liner).
    # NULL for rows translated before this field shipped, or when the
    # source alert has no why -- lookup falls back to the English why.
    why = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    alert_company = relationship("AlertCompany")


class AlertTranslation(Base):
    """Translated Alert.summary_short/summary_long (the spec-v2 card
    front's gist) -- alert-level, unlike ArticleTranslation (title/content,
    article-level) and AlertCompanyTranslation (per-company reasoning).
    Written by the same translate_pending_alerts job pass; silent English
    fallback when a row is missing, same as every other translation
    lookup."""
    __tablename__ = "alert_translations"
    __table_args__ = (UniqueConstraint("alert_id", "lang", name="uq_alert_translation_lang"),)

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    lang = Column(String, nullable=False)
    summary_short = Column(String, nullable=True)
    summary_long = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    alert = relationship("Alert")


class CategoryTranslation(Base):
    __tablename__ = "category_translations"
    __table_args__ = (UniqueConstraint("category", "lang", name="uq_category_translation_lang"),)

    id = Column(Integer, primary_key=True)
    category = Column(String, nullable=False)  # raw English category text -- the key, not an FK
    lang = Column(String, nullable=False)
    label = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class TranslationFailure(Base):
    """Retry-cap bookkeeping so an alert whose translation call keeps failing
    (bad content, model keeps refusing the schema) doesn't get retried by the
    scheduler job forever -- once attempts hits MAX_TRANSLATION_ATTEMPTS
    (see app/translation/job.py) it's skipped, and the silent English
    fallback in app/translation/lookup.py serves it indefinitely."""
    __tablename__ = "translation_failures"
    __table_args__ = (UniqueConstraint("alert_id", name="uq_translation_failure_alert"),)

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    last_attempted_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class CompanyExposure(Base):
    """One (company, exposure-dimension) ordinal rating (cost-opt spec
    2026-08-12 P3). Levels are ORDINAL by design -- NONE/LOW/MEDIUM/HIGH/
    VERY_HIGH/UNKNOWN -- never fake percentages. Rows come from
    deterministic archetype seeding (source='archetype:<version>') and from
    verified production learning folded out of CompanyNodeExposure
    (source='learned'); manual curation may override (source='manual',
    which seeding never overwrites)."""
    __tablename__ = "company_exposures"
    __table_args__ = (
        UniqueConstraint("company_id", "dimension", name="uq_company_exposure_dimension"),
    )

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    dimension = Column(String, nullable=False)  # e.g. crude_linked_inputs, consumer_demand
    level = Column(String, nullable=False)      # NONE|LOW|MEDIUM|HIGH|VERY_HIGH|UNKNOWN
    source = Column(String, nullable=False)     # archetype:<ver> | learned | manual
    version = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    company = relationship("Company", foreign_keys=[company_id])


class LLMCallUsage(Base):
    """One row per LLM call: which call it was, which model and tier served
    it, and what it actually cost in tokens (docs: cost-optimization phase
    6). Written by app.analysis.usage_log, which is called from the client
    adapters, so every provider path is covered by construction rather than
    by remembering to instrument each call site.

    Deliberately append-only and unlinked to alerts/articles: this is
    operational cost telemetry, not product data, and joining it to an
    alert would make it a retention concern it has no reason to be.
    Persistence is off unless settings.llm_usage_db_logging is set -- the
    structured log line is always emitted.
    """
    __tablename__ = "llm_call_usage"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    # The logical call, e.g. "extract_facts" / "impact_whys" -- see
    # app.config.LLM_TIERABLE_CALLS and LLM_PROTECTED_CALLS.
    call_name = Column(String, nullable=True)
    provider = Column(String, nullable=False)  # gemini | groq | anthropic
    model = Column(String, nullable=True)
    tier = Column(String, nullable=True)  # reasoning | cheap
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    # Prompt-cache accounting (phase 2). cache_read_tokens are input tokens
    # served from a warm cache (billed at a discount); cache_write_tokens
    # are the ones that populated it. Both NULL for a provider that reports
    # no cache breakdown, which is not the same as a cache miss -- a null
    # means "unknown", a zero means "measured, nothing cached".
    cache_read_tokens = Column(Integer, nullable=True)
    cache_write_tokens = Column(Integer, nullable=True)
    # Per-call observability (architecture upgrade 2026-08-12 §30): stage,
    # thinking spend, latency and the article the call served -- what the
    # cost-audit table is built from. All NULL on legacy rows and on
    # providers that don't report the field.
    article_id = Column(Integer, nullable=True)
    stage = Column(String, nullable=True)
    thinking_level = Column(String, nullable=True)
    thinking_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    success = Column(Integer, nullable=True)  # 1 | 0 | NULL (legacy path)
    # Knowledge-architecture telemetry (cost-opt spec 2026-08-12 P1): what
    # the call was FOR, not just what it cost. cache_hit=1 rows are
    # zero-token stage-cache replays -- excluded from spend sums by
    # construction (their token fields are 0).
    parent_node = Column(String, nullable=True)
    mechanism_id = Column(String, nullable=True)
    candidate_count = Column(Integer, nullable=True)
    returned_count = Column(Integer, nullable=True)
    cache_hit = Column(Integer, nullable=True)
    prompt_version = Column(String, nullable=True)
    schema_version = Column(String, nullable=True)
    estimated_cost_usd = Column(Float, nullable=True)
