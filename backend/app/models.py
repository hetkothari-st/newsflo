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
    index_tier = Column(String, nullable=False)  # NIFTY50 | NIFTY100 | NIFTY500 | OTHER
    market_cap = Column(Float, nullable=True)
    isin = Column(String, nullable=True, unique=True)


class CompanyIndexMembership(Base):
    __tablename__ = "company_index_memberships"
    __table_args__ = (UniqueConstraint("company_id", "index_code", name="uq_company_index"),)

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    index_code = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    company = relationship("Company")


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

    alerts = relationship("Alert", back_populates="article")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    category = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    article = relationship("Article", back_populates="alerts")
    companies = relationship("AlertCompany", back_populates="alert")


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
    basis = Column(String, nullable=False)  # direct_mention | sector_inference
    confidence = Column(String, nullable=False, default="llm_estimate")  # llm_estimate | calibrated

    alert = relationship("Alert", back_populates="companies")
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
