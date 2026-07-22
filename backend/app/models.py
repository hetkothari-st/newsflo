from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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


class CompanyIndexMembership(Base):
    __tablename__ = "company_index_memberships"
    __table_args__ = (UniqueConstraint("company_id", "index_code", name="uq_company_index"),)

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    index_code = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    company = relationship("Company")


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
    __table_args__ = (UniqueConstraint("url", name="uq_articles_url"),)

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

    alerts = relationship("Alert", back_populates="article")


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
    rationale = Column(Text, nullable=False)
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

    alert = relationship("Alert", back_populates="companies")
    company = relationship("Company", foreign_keys=[company_id])
    parent_company = relationship("Company", foreign_keys=[parent_company_id])


class CascadeGap(Base):
    """A cascade-company lookup (app.analysis.cascade) that failed even
    after a retry -- recorded instead of silently dropped, so the user can
    always see "this ripple path was considered and could not be
    resolved" rather than a difference between runs that looks like a
    missing feature. See app.analysis.cascade._identify_cascade_companies_per_sector."""
    __tablename__ = "cascade_gaps"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    sector = Column(String, nullable=False)
    impact_level = Column(String, nullable=False)
    # The per-sector cascade call chains from a POOL of parent companies,
    # not one -- null here, not misleadingly picking just the first parent.
    # See the comment at the call site in _identify_cascade_companies_per_sector.
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

    alert = relationship("Alert", back_populates="impact_edges")


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
    excess_move_pct = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    avg_volume_20d = Column(Float, nullable=True)
    volume_multiple = Column(Float, nullable=True)
    measured_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    measurement_status = Column(String, nullable=False)  # ok | no_data | stale

    alert = relationship("Alert")
    company = relationship("Company")


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
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    alert_company = relationship("AlertCompany")


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
