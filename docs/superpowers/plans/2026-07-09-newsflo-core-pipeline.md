# NewsFlo Core Pipeline Implementation Plan (Plan 1 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core news→impact pipeline: ingest RSS news, filter noise, call Claude to identify affected companies (direct + sector-inferred), resolve them against a real company/index database, and expose the result via a basic API + plain HTML dashboard. No calibration DB, no holdings/alerts, no CRED-style UI yet — those are Plans 2-4.

**Architecture:** Python/FastAPI modular monolith, one module per pipeline stage (ingestion, filtering, analysis, company resolution), SQLAlchemy models backed by SQLite in tests and Postgres in production, orchestrated by a single `process_new_articles()` pipeline function that later plans will hook a scheduler onto.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, `anthropic` SDK (Claude tool-use for structured output), `feedparser` (RSS), `pytest` + `httpx` (testing).

## Global Constraints

- Database schema must stay portable between SQLite (tests) and PostgreSQL (production) — no native Postgres-only column types (no `ENUM`, no `ARRAY`); enums are plain `String` columns validated in Python.
- No live network calls in any test — news fetching, Claude API calls, and (in later plans) price lookups are always mocked/monkeypatched.
- News sources for v1 are free RSS/APIs only (per spec) — no paid data sources.
- Market focus is Indian stocks (NSE/BSE) for v1 — tickers use `.NS` suffix.
- Claude structured output must go through forced tool-use (a `record_analysis` tool), never free-text JSON parsing.
- Company sector values are constrained to a fixed taxonomy (`oil_gas`, `banking`, `auto`, `it`, `pharma`, `fmcg`, `metals`, `telecom`, `infra`, `other`) so sector-based company resolution is an exact match, not fuzzy text matching.
- Frontend for this plan is a single static HTML/JS page (no React/build step) — the full CRED-style UI is Plan 4.
- One commit per task, at the end of that task's steps.

---

## Task 1: Project Scaffolding & Core DB Models

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/pytest.ini`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/db.py`
- Create: `backend/app/models.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `Base` (SQLAlchemy declarative base, `app.db`), `get_engine(url: str | None = None)` (`app.db`), `SessionLocal` (sessionmaker, `app.db`), `settings` (`app.config`), models `Company`, `Article`, `Alert`, `AlertCompany` (`app.models`) with fields exactly as defined below — every later task relies on these field names.

- [ ] **Step 1: Set up the project skeleton**

Create `backend/requirements.txt`:

```
fastapi
uvicorn
sqlalchemy
pydantic
pydantic-settings
anthropic
feedparser
httpx
pytest
```

Create `backend/pytest.ini`:

```ini
[pytest]
pythonpath = .
```

From `backend/`, create a virtualenv and install:

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```

- [ ] **Step 2: Write the failing test**

`backend/tests/conftest.py`:

```python
import pytest
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_engine
from app import models  # noqa: F401  ensures models are registered on Base


@pytest.fixture()
def db_session():
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
```

`backend/tests/test_models.py`:

```python
import pytest

from app.models import Article, Company


def test_create_company(db_session):
    company = Company(
        ticker="RELIANCE.NS", name="Reliance Industries",
        sector="oil_gas", index_tier="NIFTY50", market_cap=1_800_000.0,
    )
    db_session.add(company)
    db_session.commit()

    fetched = db_session.query(Company).filter_by(ticker="RELIANCE.NS").one()
    assert fetched.name == "Reliance Industries"
    assert fetched.index_tier == "NIFTY50"


def test_article_url_is_unique(db_session):
    db_session.add(Article(source="moneycontrol", url="https://example.com/a", title="Headline 1"))
    db_session.commit()

    db_session.add(Article(source="moneycontrol", url="https://example.com/a", title="Duplicate"))
    with pytest.raises(Exception):
        db_session.commit()
```

Also create empty `backend/tests/__init__.py` and `backend/app/__init__.py`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db'` (or `app.models`).

- [ ] **Step 4: Implement `app/config.py`, `app/db.py`, `app/models.py`**

`backend/app/config.py`:

```python
import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")


settings = Settings()
```

`backend/app/db.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

Base = declarative_base()


def get_engine(url: str | None = None):
    url = url or settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


engine = get_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
```

`backend/app/models.py`:

```python
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
    published_at = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, nullable=False, default=utcnow)
    status = Column(String, nullable=False, default="NEW")  # NEW|FILTERED|CATEGORIZED|ANALYZED|ANALYSIS_FAILED
    category = Column(String, nullable=True)

    alerts = relationship("Alert", back_populates="article")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    category = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)

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

    alert = relationship("Alert", back_populates="companies")
    company = relationship("Company")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest tests/test_models.py -v`
Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/pytest.ini backend/app backend/tests
git commit -m "feat: scaffold project and core DB models"
```

---

## Task 2: Company Master Data Loader

**Files:**
- Create: `backend/app/companies/__init__.py`
- Create: `backend/app/companies/loader.py`
- Test: `backend/tests/test_loader.py`

**Interfaces:**
- Consumes: `Company` model (`app.models`, Task 1).
- Produces: `load_companies_from_csv(session: Session, csv_path: str, index_tier: str) -> int` (`app.companies.loader`) — later tasks (resolution, ops scripts) rely on `Company.sector` values being one of the fixed taxonomy this function normalizes to.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_loader.py`:

```python
import csv

from app.companies.loader import load_companies_from_csv
from app.models import Company


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["Symbol", "Company Name", "Industry"])
        writer.writeheader()
        writer.writerows(rows)


def test_load_companies_from_csv_inserts_rows(db_session, tmp_path):
    csv_path = tmp_path / "nifty50.csv"
    _write_csv(csv_path, [
        {"Symbol": "RELIANCE", "Company Name": "Reliance Industries", "Industry": "Petroleum Products"},
        {"Symbol": "HDFCBANK", "Company Name": "HDFC Bank", "Industry": "Banks"},
    ])

    count = load_companies_from_csv(db_session, str(csv_path), index_tier="NIFTY50")

    assert count == 2
    reliance = db_session.query(Company).filter_by(ticker="RELIANCE.NS").one()
    assert reliance.sector == "oil_gas"
    assert reliance.index_tier == "NIFTY50"


def test_load_companies_from_csv_upserts_on_rerun(db_session, tmp_path):
    csv_path = tmp_path / "nifty50.csv"
    _write_csv(csv_path, [{"Symbol": "RELIANCE", "Company Name": "Reliance Industries", "Industry": "Petroleum Products"}])
    load_companies_from_csv(db_session, str(csv_path), index_tier="NIFTY50")

    _write_csv(csv_path, [{"Symbol": "RELIANCE", "Company Name": "Reliance Industries Ltd", "Industry": "Petroleum Products"}])
    load_companies_from_csv(db_session, str(csv_path), index_tier="NIFTY50")

    companies = db_session.query(Company).filter_by(ticker="RELIANCE.NS").all()
    assert len(companies) == 1
    assert companies[0].name == "Reliance Industries Ltd"


def test_load_companies_from_csv_defaults_unknown_industry_to_other(db_session, tmp_path):
    csv_path = tmp_path / "nifty50.csv"
    _write_csv(csv_path, [{"Symbol": "WEIRDCO", "Company Name": "Weird Co", "Industry": "Something Unrecognized"}])

    load_companies_from_csv(db_session, str(csv_path), index_tier="NIFTY50")

    company = db_session.query(Company).filter_by(ticker="WEIRDCO.NS").one()
    assert company.sector == "other"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies'`

- [ ] **Step 3: Implement the loader**

`backend/app/companies/__init__.py`: empty file.

`backend/app/companies/loader.py`:

```python
import csv

from sqlalchemy.orm import Session

from app.models import Company

SECTOR_MAP = {
    "oil": "oil_gas", "gas": "oil_gas", "petroleum": "oil_gas",
    "bank": "banking", "financial": "banking",
    "automobile": "auto", "auto": "auto",
    "software": "it", "information technology": "it",
    "pharmaceutical": "pharma", "healthcare": "pharma",
    "fmcg": "fmcg", "consumer": "fmcg",
    "metal": "metals", "mining": "metals",
    "telecom": "telecom",
    "infrastructure": "infra", "construction": "infra", "power": "infra",
}


def _normalize_sector(industry: str) -> str:
    lowered = industry.strip().lower()
    for keyword, sector in SECTOR_MAP.items():
        if keyword in lowered:
            return sector
    return "other"


def load_companies_from_csv(session: Session, csv_path: str, index_tier: str) -> int:
    count = 0
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ticker = f"{row['Symbol'].strip()}.NS"
            sector = _normalize_sector(row["Industry"])
            name = row["Company Name"].strip()

            existing = session.query(Company).filter_by(ticker=ticker).one_or_none()
            if existing:
                existing.name = name
                existing.sector = sector
                existing.index_tier = index_tier
            else:
                session.add(Company(ticker=ticker, name=name, sector=sector, index_tier=index_tier))
            count += 1
    session.commit()
    return count
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_loader.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies backend/tests/test_loader.py
git commit -m "feat: load company master data from NSE index CSVs"
```

---

## Task 3: News Ingestion (RSS Poller)

**Files:**
- Create: `backend/app/ingestion/__init__.py`
- Create: `backend/app/ingestion/sources.py`
- Create: `backend/app/ingestion/poller.py`
- Test: `backend/tests/test_poller.py`

**Interfaces:**
- Consumes: `Article` model (`app.models`, Task 1).
- Produces: `RSS_FEEDS: list[dict]` (`app.ingestion.sources`), `fetch_new_articles(session: Session, feeds: list[dict]) -> int` (`app.ingestion.poller`) — returns count of newly inserted articles, deduped by URL.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_poller.py`:

```python
from types import SimpleNamespace

from app.ingestion.poller import fetch_new_articles


def test_fetch_new_articles_inserts_and_dedupes(db_session, monkeypatch):
    feed_entries = [
        {"link": "https://example.com/a", "title": "Story A", "summary": "..."},
        {"link": "https://example.com/a", "title": "Story A duplicate", "summary": "..."},
    ]

    def fake_parse(url):
        return SimpleNamespace(entries=feed_entries)

    monkeypatch.setattr("app.ingestion.poller.feedparser.parse", fake_parse)

    feeds = [{"source": "test_source", "url": "http://feed.test/rss"}]

    inserted = fetch_new_articles(db_session, feeds)
    assert inserted == 1

    inserted_again = fetch_new_articles(db_session, feeds)
    assert inserted_again == 0


def test_fetch_new_articles_skips_entries_without_link(db_session, monkeypatch):
    def fake_parse(url):
        return SimpleNamespace(entries=[{"title": "No link here", "summary": ""}])

    monkeypatch.setattr("app.ingestion.poller.feedparser.parse", fake_parse)

    inserted = fetch_new_articles(db_session, [{"source": "test_source", "url": "http://feed.test/rss"}])
    assert inserted == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_poller.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion'`

- [ ] **Step 3: Implement ingestion**

`backend/app/ingestion/__init__.py`: empty file.

`backend/app/ingestion/sources.py`:

```python
RSS_FEEDS = [
    {"source": "economic_times", "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"},
    {"source": "moneycontrol", "url": "https://www.moneycontrol.com/rss/marketreports.xml"},
    {"source": "business_standard", "url": "https://www.business-standard.com/rss/markets-106.rss"},
]
```

`backend/app/ingestion/poller.py`:

```python
from datetime import datetime, timezone

import feedparser
from sqlalchemy.orm import Session

from app.models import Article


def _parse_published(entry) -> datetime | None:
    published_parsed = entry.get("published_parsed")
    if published_parsed:
        return datetime(*published_parsed[:6], tzinfo=timezone.utc)
    return None


def fetch_new_articles(session: Session, feeds: list[dict]) -> int:
    inserted = 0
    for feed in feeds:
        parsed = feedparser.parse(feed["url"])
        for entry in parsed.entries:
            url = entry.get("link")
            if not url:
                continue
            if session.query(Article).filter_by(url=url).one_or_none():
                continue
            session.add(Article(
                source=feed["source"],
                url=url,
                title=entry.get("title", ""),
                content=entry.get("summary", ""),
                published_at=_parse_published(entry),
                status="NEW",
            ))
            inserted += 1
    session.commit()
    return inserted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_poller.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion backend/tests/test_poller.py
git commit -m "feat: add RSS ingestion poller with URL dedup"
```

---

## Task 4: Filter Heuristic

**Files:**
- Create: `backend/app/filtering/__init__.py`
- Create: `backend/app/filtering/heuristic.py`
- Test: `backend/tests/test_heuristic.py`

**Interfaces:**
- Consumes: `Article` model (`app.models`, Task 1).
- Produces: `classify_category(title: str, content: str) -> str | None` and `filter_new_articles(session: Session) -> None` (`app.filtering.heuristic`) — sets `Article.status` to `"CATEGORIZED"` (with `Article.category` set) or `"FILTERED"`. Task 7 (pipeline) calls `filter_new_articles` directly.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_heuristic.py`:

```python
from app.filtering.heuristic import classify_category, filter_new_articles
from app.models import Article


def test_classify_category_matches_oil_keyword():
    assert classify_category("US strikes Iran oil export sites", "") == "oil_energy"


def test_classify_category_returns_none_for_irrelevant_text():
    assert classify_category("Local bakery wins award", "") is None


def test_filter_new_articles_updates_status(db_session):
    relevant = Article(source="test", url="https://example.com/1", title="RBI hikes repo rate", content="")
    irrelevant = Article(source="test", url="https://example.com/2", title="Cat stuck in tree", content="")
    db_session.add_all([relevant, irrelevant])
    db_session.commit()

    filter_new_articles(db_session)

    db_session.refresh(relevant)
    db_session.refresh(irrelevant)
    assert relevant.status == "CATEGORIZED"
    assert relevant.category == "banking"
    assert irrelevant.status == "FILTERED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_heuristic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.filtering'`

- [ ] **Step 3: Implement the heuristic**

`backend/app/filtering/__init__.py`: empty file.

`backend/app/filtering/heuristic.py`:

```python
from sqlalchemy.orm import Session

from app.models import Article

CATEGORY_KEYWORDS = {
    "oil_energy": ["crude", "oil", "opec", "brent", "petroleum", "refinery"],
    "banking": ["rbi", "repo rate", "interest rate", "npa"],
    "auto_ev": ["ev subsidy", "electric vehicle", "fame scheme", "auto sales"],
    "geopolitics": ["sanction", "strike", "conflict", "tariff", "export ban", "war"],
}


def classify_category(title: str, content: str) -> str | None:
    text = f"{title} {content}".lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return None


def filter_new_articles(session: Session) -> None:
    for article in session.query(Article).filter_by(status="NEW").all():
        category = classify_category(article.title, article.content)
        if category is None:
            article.status = "FILTERED"
        else:
            article.status = "CATEGORIZED"
            article.category = category
    session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_heuristic.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/filtering backend/tests/test_heuristic.py
git commit -m "feat: add keyword-based category filter heuristic"
```

---

## Task 5: Claude Analysis Client

**Files:**
- Create: `backend/app/analysis/__init__.py`
- Create: `backend/app/analysis/schemas.py`
- Create: `backend/app/analysis/claude_client.py`
- Test: `backend/tests/test_claude_client.py`

**Interfaces:**
- Produces: `SECTORS: list[str]`, `CompanyMention` (Pydantic model: `name: str`, `ticker: str | None`, `is_direct: bool`, `sector: str | None`, `direction: str`, `magnitude_low: float`, `magnitude_high: float`, `rationale: str`), `AnalysisOutput` (Pydantic model: `category: str`, `companies: list[CompanyMention]`) — both in `app.analysis.schemas`. `build_client(api_key: str)` and `analyze_article(client, title: str, content: str) -> AnalysisOutput` in `app.analysis.claude_client`. Task 6 (resolution) and Task 7 (pipeline) both import from here.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_claude_client.py`:

```python
from types import SimpleNamespace

from app.analysis.claude_client import analyze_article


class FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, input_data):
        self.input = input_data


class FakeMessages:
    def __init__(self, response_input):
        self._response_input = response_input

    def create(self, **kwargs):
        return SimpleNamespace(content=[FakeToolUseBlock(self._response_input)])


class FakeClient:
    def __init__(self, response_input):
        self.messages = FakeMessages(response_input)


def test_analyze_article_parses_direct_mention():
    fake_output = {
        "category": "oil_energy",
        "companies": [{
            "name": "Reliance Industries", "ticker": "RELIANCE.NS", "is_direct": True, "sector": None,
            "direction": "bullish", "magnitude_low": 2.0, "magnitude_high": 4.0,
            "rationale": "Top refiner benefits from crude price spike.",
        }],
    }
    client = FakeClient(fake_output)

    result = analyze_article(client, title="US strikes Iran oil sites", content="crude oil markets react")

    assert result.category == "oil_energy"
    assert result.companies[0].ticker == "RELIANCE.NS"
    assert result.companies[0].direction == "bullish"


def test_analyze_article_parses_sector_mention():
    fake_output = {
        "category": "oil_energy",
        "companies": [{
            "name": "oil refiners", "ticker": None, "is_direct": False, "sector": "oil_gas",
            "direction": "bullish", "magnitude_low": 1.0, "magnitude_high": 2.0,
            "rationale": "Sector-wide margin expansion.",
        }],
    }
    client = FakeClient(fake_output)

    result = analyze_article(client, title="Crude prices spike globally", content="")

    assert result.companies[0].is_direct is False
    assert result.companies[0].sector == "oil_gas"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_claude_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis'`

- [ ] **Step 3: Implement schemas and client**

`backend/app/analysis/__init__.py`: empty file.

`backend/app/analysis/schemas.py`:

```python
from typing import Optional

from pydantic import BaseModel

SECTORS = ["oil_gas", "banking", "auto", "it", "pharma", "fmcg", "metals", "telecom", "infra", "other"]


class CompanyMention(BaseModel):
    name: str
    ticker: Optional[str] = None
    is_direct: bool
    sector: Optional[str] = None
    direction: str  # bullish | bearish
    magnitude_low: float
    magnitude_high: float
    rationale: str


class AnalysisOutput(BaseModel):
    category: str
    companies: list[CompanyMention]
```

`backend/app/analysis/claude_client.py`:

```python
from anthropic import Anthropic

from app.analysis.schemas import SECTORS, AnalysisOutput

MODEL = "claude-sonnet-4-5"

RECORD_ANALYSIS_TOOL = {
    "name": "record_analysis",
    "description": "Record which companies are affected by this news article and how.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "companies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "ticker": {"type": ["string", "null"]},
                        "is_direct": {"type": "boolean"},
                        "sector": {"type": ["string", "null"], "enum": SECTORS + [None]},
                        "direction": {"type": "string", "enum": ["bullish", "bearish"]},
                        "magnitude_low": {"type": "number"},
                        "magnitude_high": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["name", "is_direct", "direction", "magnitude_low", "magnitude_high", "rationale"],
                },
            },
        },
        "required": ["category", "companies"],
    },
}


def build_client(api_key: str) -> Anthropic:
    return Anthropic(api_key=api_key)


def analyze_article(client, title: str, content: str) -> AnalysisOutput:
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        tools=[RECORD_ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "record_analysis"},
        messages=[{
            "role": "user",
            "content": (
                "Analyze this financial news article. Identify which companies are directly "
                "named and which sectors are indirectly affected, with direction and an "
                "estimated percentage price-move range.\n\n"
                f"Title: {title}\n\nContent: {content}"
            ),
        }],
    )
    tool_use = next(block for block in message.content if block.type == "tool_use")
    return AnalysisOutput.model_validate(tool_use.input)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_claude_client.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis backend/tests/test_claude_client.py
git commit -m "feat: add Claude tool-use client for article impact analysis"
```

---

## Task 6: Company Resolution

**Files:**
- Create: `backend/app/companies/resolution.py`
- Test: `backend/tests/test_resolution.py`

**Interfaces:**
- Consumes: `Company` model (Task 1), `CompanyMention` (Task 5).
- Produces: `resolve_companies(session: Session, mentions: list[CompanyMention]) -> list[dict]` (`app.companies.resolution`) — each dict has keys `company_id`, `direction`, `magnitude_low`, `magnitude_high`, `rationale`, `basis` (`"direct_mention"` or `"sector_inference"`), matching `AlertCompany` columns exactly so Task 7 can pass them straight into `AlertCompany(**entry)`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_resolution.py`:

```python
from app.analysis.schemas import CompanyMention
from app.companies.resolution import resolve_companies
from app.models import Company


def _make_company(session, ticker, name, sector, market_cap):
    company = Company(ticker=ticker, name=name, sector=sector, index_tier="NIFTY50", market_cap=market_cap)
    session.add(company)
    session.commit()
    return company


def test_resolve_direct_mention(db_session):
    company = _make_company(db_session, "RELIANCE.NS", "Reliance Industries", "oil_gas", 1_800_000.0)
    mention = CompanyMention(
        name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
        direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
    )

    resolved = resolve_companies(db_session, [mention])

    assert len(resolved) == 1
    assert resolved[0]["company_id"] == company.id
    assert resolved[0]["basis"] == "direct_mention"


def test_resolve_sector_inference_picks_top_5_by_market_cap(db_session):
    for i in range(7):
        _make_company(db_session, f"OIL{i}.NS", f"Oil Co {i}", "oil_gas", market_cap=float(7 - i))
    mention = CompanyMention(
        name="oil sector", ticker=None, is_direct=False, sector="oil_gas",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="crude spike",
    )

    resolved = resolve_companies(db_session, [mention])

    assert len(resolved) == 5
    assert all(r["basis"] == "sector_inference" for r in resolved)


def test_resolve_direct_mention_with_unknown_ticker_is_skipped(db_session):
    mention = CompanyMention(
        name="Unknown Corp", ticker="UNKNOWN.NS", is_direct=True, sector=None,
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="n/a",
    )

    resolved = resolve_companies(db_session, [mention])

    assert resolved == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_resolution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.resolution'`

- [ ] **Step 3: Implement resolution**

`backend/app/companies/resolution.py`:

```python
from sqlalchemy.orm import Session

from app.analysis.schemas import CompanyMention
from app.models import Company

TOP_N_SECTOR_COMPANIES = 5


def _to_resolved(company: Company, mention: CompanyMention, basis: str) -> dict:
    return {
        "company_id": company.id,
        "direction": mention.direction,
        "magnitude_low": mention.magnitude_low,
        "magnitude_high": mention.magnitude_high,
        "rationale": mention.rationale,
        "basis": basis,
    }


def resolve_companies(session: Session, mentions: list[CompanyMention]) -> list[dict]:
    resolved = []
    for mention in mentions:
        if mention.is_direct:
            if not mention.ticker:
                continue
            company = session.query(Company).filter_by(ticker=mention.ticker).one_or_none()
            if company is None:
                continue
            resolved.append(_to_resolved(company, mention, basis="direct_mention"))
        else:
            if not mention.sector:
                continue
            companies = (
                session.query(Company)
                .filter_by(sector=mention.sector)
                .order_by(Company.market_cap.desc())
                .limit(TOP_N_SECTOR_COMPANIES)
                .all()
            )
            for company in companies:
                resolved.append(_to_resolved(company, mention, basis="sector_inference"))
    return resolved
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_resolution.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/resolution.py backend/tests/test_resolution.py
git commit -m "feat: resolve direct and sector-inferred company mentions"
```

---

## Task 7: Pipeline Orchestration

**Files:**
- Create: `backend/app/pipeline.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `filter_new_articles` (Task 4), `analyze_article` (Task 5, imported by name so tests can monkeypatch it inside `app.pipeline`), `resolve_companies` (Task 6), `Alert`/`AlertCompany`/`Article` models (Task 1).
- Produces: `process_new_articles(session: Session, claude_client) -> int` (`app.pipeline`) — returns count of alerts created. Task 8 (API) reads what this writes; Task 9 (scheduler wiring, later plan) calls this function directly.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_pipeline.py`:

```python
import app.pipeline as pipeline_module
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.models import Alert, AlertCompany, Article, Company
from app.pipeline import process_new_articles


def test_process_new_articles_creates_alert_end_to_end(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/a",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert = db_session.query(Alert).one()
    assert alert.category == "oil_energy"

    alert_companies = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    assert len(alert_companies) == 1
    assert alert_companies[0].company_id == company.id

    refreshed_article = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed_article.status == "ANALYZED"


def test_process_new_articles_marks_analysis_failed_after_retries(db_session, monkeypatch):
    article = Article(source="test", url="https://example.com/b", title="RBI hikes repo rate", content="")
    db_session.add(article)
    db_session.commit()

    def boom(client, title, content):
        raise RuntimeError("api down")

    monkeypatch.setattr(pipeline_module, "analyze_article", boom)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 0
    refreshed = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed.status == "ANALYSIS_FAILED"


def test_process_new_articles_ignores_filtered_articles(db_session, monkeypatch):
    irrelevant = Article(source="test", url="https://example.com/c", title="Cat stuck in tree", content="")
    db_session.add(irrelevant)
    db_session.commit()

    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: (_ for _ in ()).throw(AssertionError("should not be called")))

    created = process_new_articles(db_session, claude_client=object())

    assert created == 0
    refreshed = db_session.query(Article).filter_by(id=irrelevant.id).one()
    assert refreshed.status == "FILTERED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline'`

- [ ] **Step 3: Implement the pipeline**

`backend/app/pipeline.py`:

```python
from sqlalchemy.orm import Session

from app.analysis.claude_client import analyze_article
from app.companies.resolution import resolve_companies
from app.filtering.heuristic import filter_new_articles
from app.models import Alert, AlertCompany, Article


def process_new_articles(session: Session, claude_client) -> int:
    filter_new_articles(session)

    alerts_created = 0
    pending = session.query(Article).filter_by(status="CATEGORIZED").all()

    for article in pending:
        analysis = None
        for _ in range(2):  # try once, retry once
            try:
                analysis = analyze_article(claude_client, article.title, article.content)
                break
            except Exception:
                continue

        if analysis is None:
            article.status = "ANALYSIS_FAILED"
            session.commit()
            continue

        resolved = resolve_companies(session, analysis.companies)

        alert = Alert(article_id=article.id, category=analysis.category)
        session.add(alert)
        session.flush()

        for entry in resolved:
            session.add(AlertCompany(alert_id=alert.id, **entry))

        article.status = "ANALYZED"
        article.category = analysis.category
        session.commit()
        alerts_created += 1

    return alerts_created
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_pipeline.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: wire filter, analysis, and resolution into pipeline orchestration"
```

---

## Task 8: API Layer

**Files:**
- Create: `backend/app/routers/__init__.py`
- Create: `backend/app/routers/articles.py`
- Create: `backend/app/routers/alerts.py`
- Create: `backend/app/main.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `SessionLocal` (Task 1), `Article`/`Alert`/`AlertCompany`/`Company` models (Task 1).
- Produces: `get_db()` dependency (`app.routers.articles`, reused by `app.routers.alerts`), FastAPI `app` (`app.main`) with `GET /api/articles` and `GET /api/alerts` — Task 9's static dashboard fetches these two endpoints by exact path.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, AlertCompany, Article, Company
from app.routers.articles import get_db


def test_list_alerts_returns_nested_companies(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(
        source="test", url="https://example.com/x", title="Test headline",
        status="ANALYZED", category="oil_energy",
    )
    db_session.add(article)
    db_session.commit()

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin", basis="direct_mention",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["companies"][0]["ticker"] == "RELIANCE.NS"
    assert body[0]["article"]["title"] == "Test headline"

    app.dependency_overrides.clear()


def test_list_articles_returns_all(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    db_session.add(Article(source="test", url="https://example.com/y", title="Another headline"))
    db_session.commit()

    response = client.get("/api/articles")

    assert response.status_code == 200
    assert response.json()[0]["title"] == "Another headline"

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Implement the API**

`backend/app/routers/__init__.py`: empty file.

`backend/app/routers/articles.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Article

router = APIRouter(prefix="/api/articles", tags=["articles"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def list_articles(db: Session = Depends(get_db)):
    articles = db.query(Article).order_by(Article.fetched_at.desc()).all()
    return [{
        "id": a.id, "source": a.source, "title": a.title, "url": a.url,
        "status": a.status, "category": a.category,
        "fetched_at": a.fetched_at.isoformat() if a.fetched_at else None,
    } for a in articles]
```

`backend/app/routers/alerts.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.models import Alert
from app.routers.articles import get_db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(db: Session = Depends(get_db)):
    alerts = db.query(Alert).order_by(Alert.created_at.desc()).all()
    return [{
        "id": alert.id,
        "category": alert.category,
        "created_at": alert.created_at.isoformat(),
        "article": {"id": alert.article.id, "title": alert.article.title, "url": alert.article.url},
        "companies": [{
            "company_id": ac.company_id, "ticker": ac.company.ticker, "name": ac.company.name,
            "index_tier": ac.company.index_tier, "direction": ac.direction,
            "magnitude_low": ac.magnitude_low, "magnitude_high": ac.magnitude_high,
            "rationale": ac.rationale, "basis": ac.basis,
        } for ac in alert.companies],
    } for alert in alerts]
```

`backend/app/main.py`:

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import alerts, articles

app = FastAPI(title="NewsFlo")

app.include_router(articles.router)
app.include_router(alerts.router)

app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
```

Note: `StaticFiles` requires `app/static/` to exist — created in Task 9. Run this task's tests before Task 9; `TestClient` will still work even though `/` itself 404s until Task 9 adds `index.html`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && mkdir -p app/static && touch app/static/.gitkeep && .venv/Scripts/pytest tests/test_api.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers backend/app/main.py backend/app/static/.gitkeep backend/tests/test_api.py
git commit -m "feat: add articles and alerts API endpoints"
```

---

## Task 9: Minimal Static Dashboard

**Files:**
- Create: `backend/app/static/index.html`

**Interfaces:**
- Consumes: `GET /api/alerts` (Task 8) via `fetch`.
- Produces: a served page at `/` — no interface other tasks depend on (this is the leaf of the plan).

- [ ] **Step 1: Write the page**

`backend/app/static/index.html`:

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>NewsFlo — Alerts</title>
  <style>
    body { font-family: sans-serif; background: #111; color: #eee; padding: 24px; }
    .alert { border: 1px solid #333; padding: 12px; margin-bottom: 12px; }
    .company { margin-left: 12px; font-size: 14px; }
  </style>
</head>
<body>
  <h1>NewsFlo — Live Alerts</h1>
  <div id="alerts">Loading...</div>
  <script>
    async function load() {
      const res = await fetch('/api/alerts');
      const alerts = await res.json();
      const container = document.getElementById('alerts');
      if (alerts.length === 0) {
        container.textContent = 'No alerts yet.';
        return;
      }
      container.innerHTML = alerts.map(a => `
        <div class="alert">
          <strong>${a.article.title}</strong> (${a.category})
          ${a.companies.map(c => `<div class="company">${c.name || c.ticker} [${c.index_tier}] ${c.direction} ${c.magnitude_low}-${c.magnitude_high}% — ${c.rationale}</div>`).join('')}
        </div>
      `).join('');
    }
    load();
  </script>
</body>
</html>
```

- [ ] **Step 2: Verify manually**

Run: `cd backend && .venv/Scripts/uvicorn app.main:app --reload`

Open `http://127.0.0.1:8000/` in a browser — expect "No alerts yet." (empty DB) with no console errors, and `http://127.0.0.1:8000/api/alerts` returning `[]`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/static/index.html
git commit -m "feat: add minimal static dashboard for viewing alerts"
```

---

## Task 10: End-to-End Integration Test

**Files:**
- Test: `backend/tests/test_end_to_end.py`

**Interfaces:**
- Consumes: `fetch_new_articles` (Task 3), `process_new_articles` (Task 7), API endpoints (Task 8) — exercises the full chain in one test with no internal function calls beyond what a real deployment would run.

- [ ] **Step 1: Write the test**

`backend/tests/test_end_to_end.py`:

```python
from types import SimpleNamespace

import app.pipeline as pipeline_module
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.ingestion.poller import fetch_new_articles
from app.models import Company
from app.pipeline import process_new_articles


def test_full_pipeline_from_rss_entry_to_alert(db_session, monkeypatch):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries",
        sector="oil_gas", index_tier="NIFTY50", market_cap=1_800_000.0,
    ))
    db_session.commit()

    feed_entries = [{
        "link": "https://example.com/breaking-oil-news",
        "title": "US strikes Iran oil export sites",
        "summary": "Crude oil markets react sharply to the strikes.",
    }]

    def fake_parse(url):
        return SimpleNamespace(entries=feed_entries)

    monkeypatch.setattr("app.ingestion.poller.feedparser.parse", fake_parse)

    inserted = fetch_new_articles(db_session, [{"source": "test_feed", "url": "http://feed.test/rss"}])
    assert inserted == 1

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    from app.main import app as fastapi_app
    from app.routers.articles import get_db
    from fastapi.testclient import TestClient

    fastapi_app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(fastapi_app)

    response = client.get("/api/alerts")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["article"]["title"] == "US strikes Iran oil export sites"
    assert body[0]["companies"][0]["ticker"] == "RELIANCE.NS"

    fastapi_app.dependency_overrides.clear()
```

- [ ] **Step 2: Run the full test suite**

Run: `cd backend && .venv/Scripts/pytest tests/ -v`
Expected: all tests pass (this one plus every test from Tasks 1-8), no live network calls made.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_end_to_end.py
git commit -m "test: add end-to-end pipeline integration test"
```

---

## Definition of Done (Plan 1)

- `pytest tests/ -v` passes fully with zero live network calls.
- Running `uvicorn app.main:app` and manually inserting a `Company` + a fake `Article`, then calling `process_new_articles` (e.g. via a Python shell) with a real `ANTHROPIC_API_KEY`, produces a real Claude-analyzed `Alert` visible at `/api/alerts` and on the static dashboard at `/`.
- Company master data can be loaded from a real NSE index CSV via `load_companies_from_csv`.
- This plan deliberately excludes: calibration/outcomes DB (Plan 2), holdings/auth/email alerts (Plan 3), CRED-style React UI + WebSocket live push (Plan 4).
