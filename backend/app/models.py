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


class Holding(Base):
    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_holdings_user_company"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    quantity = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
