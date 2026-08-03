# Full NSE + BSE Stock Universe with Authentic Cap Tiers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 509-company Indian universe with every company listed on NSE or BSE (~4,967), keyed by ISIN so dual-listed companies appear once, classified from official exchange data, with market-cap tiers derived from exchange-published caps.

**Architecture:** A two-stage pipeline — network fetchers write raw snapshots to disk, then a pure normalizer and a DB loader consume those snapshots. `companies` keeps its integer PK (881 `alert_companies` rows depend on it) and gains ISIN as its natural key plus provenance columns; a new `listings` table holds per-exchange facts. The entity matcher is rebuilt on an indexed alias table before the universe grows, so resolution never runs substring matching over 5,000 names.

**Tech Stack:** Python 3, SQLAlchemy (no Alembic), pytest, FastAPI, SQLite (dev) / PostgreSQL (prod), stdlib `urllib` for fetching.

**Spec:** `docs/superpowers/specs/2026-08-03-stock-universe-cap-tiers-design.md`

## Global Constraints

- **All commands run from `backend/`.** `pytest.ini` sets `pythonpath = .`.
- **No Alembic.** New columns on existing tables MUST be appended to `_ADDED_COLUMNS` in `app/db.py` or queries raise "no such column" against older DBs. New *tables* are created automatically by `Base.metadata.create_all`.
- **`ALTER TABLE ADD COLUMN` cannot add a `CHECK` constraint in SQLite.** Deviation from spec §5.1: the `market='INDIA' → isin NOT NULL` invariant is enforced in application code (Task 15), not as a DB constraint. Added columns must be nullable or carry a `DEFAULT`.
- **No test may make a network call.** The existing suite enforces this culturally; `tests/conftest.py` already stubs outbound image fetches. Fetchers are tested only via injected fake transports.
- **Degrade, never raise.** Follow `app/market/measure.py`, `app/companies/market_caps.py`: a single failure returns `None`/skips, never aborts a batch or 500s a request.
- **Omit rather than fabricate.** An unavailable fact is `NULL` with `NULL` provenance. Never a default, never a guess.
- **`companies.id` must never change.** It is FK'd by `alert_companies`, `user_watchlist_companies`, `holdings`, `market_moves`, `car_outcomes`, `calibration_samples`, `impact_edges`.
- **Snapshot root:** `data/universe/<YYYY-MM-DD>/`. Fixtures for tests live in `tests/fixtures/universe/`.
- **Sector vocabulary is closed:** `banking, fmcg, pharma, it, oil_gas, metals, infra, auto, telecom, chemicals, defense, railways_transport, other`.
- **Tradeability vocabulary is closed:** `NORMAL, RESTRICTED, SME, SUSPENDED`.
- **Cap tier vocabulary is closed:** `LARGE, MID, SMALL, MICRO`.

## Ordering Deviation From Spec §9

The spec ordered the full ingest (step 4) before the matcher swap (step 5). This plan **inverts them**: the matcher is built and validated against the existing 509 companies (Phase 5) *before* the universe grows (Phase 7). Rationale: shipping 4,458 new companies while `_find_direct_company` still does substring matching would degrade the affected-companies section in production with no rollback smaller than a full revert. Validating the matcher against a stable universe first makes the ingest a data change rather than a behaviour change.

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `app/companies/universe/__init__.py` | package marker |
| `app/companies/universe/snapshot.py` | snapshot paths, resume state, latest-snapshot lookup. No network, no DB |
| `app/companies/universe/fetchers.py` | all network I/O; writes raw bytes to snapshot dirs |
| `app/companies/universe/normalize.py` | pure: raw dicts → canonical records. No I/O, no `app.models` import |
| `app/companies/universe/sector_map.py` | official BSE sector → 12-value bucket; tradeability derivation |
| `app/companies/universe/loader.py` | DB upserts by ISIN |
| `app/companies/matching/__init__.py` | package marker |
| `app/companies/matching/normalize.py` | company-name canonicalization. Pure |
| `app/companies/matching/curated.py` | reviewed trade-name overrides. Static data |
| `app/companies/matching/aliases.py` | builds `company_aliases` rows |
| `app/companies/matching/matcher.py` | the match ladder |
| `backfill_universe.py` | one-shot backfill of the existing 509 |
| `ingest_universe.py` | full-universe ingest runbook |

**Modify:**

| Path | Change |
|---|---|
| `app/models.py` | `Company` columns; new `Listing`, `CompanyAlias` |
| `app/db.py` | `_ADDED_COLUMNS` entries |
| `app/config.py` | staleness constants, `MICRO_CAP_RANK_CUTOFF`, matcher flag |
| `app/market/cap_tier.py` | `resolve_cap_tier`, rank-based MICRO |
| `app/companies/resolution.py` | use matcher; market-cap fan-out |

---

# Phase 1 — Schema Foundation

### Task 1: Company provenance columns, Listing and CompanyAlias models

**Files:**
- Modify: `app/models.py`
- Modify: `app/db.py:24-67` (`_ADDED_COLUMNS`)
- Test: `tests/test_universe_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Company.market`, `Company.official_sector`, `Company.official_industry`, `Company.official_igroup`, `Company.official_isubgroup`, `Company.classification_source`, `Company.classification_as_of`, `Company.market_cap_source`, `Company.market_cap_as_of`, `Company.amfi_tier`, `Company.amfi_rank`, `Company.amfi_as_of`, `Company.tradeability`; models `Listing`, `CompanyAlias`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_universe_schema.py`:

```python
from datetime import date

from app.models import Company, CompanyAlias, Listing


def _company(**kw):
    defaults = dict(ticker="TEST.NS", name="Test Ltd", sector="other", index_tier="OTHER")
    defaults.update(kw)
    return Company(**defaults)


def test_company_defaults_to_india_and_normal_tradeability(db_session):
    company = _company()
    db_session.add(company)
    db_session.commit()
    assert company.market == "INDIA"
    assert company.tradeability == "NORMAL"


def test_company_carries_official_classification_with_provenance(db_session):
    company = _company(
        official_sector="Energy",
        official_industry="Oil, Gas & Consumable Fuels",
        official_igroup="Petroleum Products",
        official_isubgroup="Refineries & Marketing",
        classification_source="BSE",
        classification_as_of=date(2026, 8, 3),
    )
    db_session.add(company)
    db_session.commit()
    assert company.official_isubgroup == "Refineries & Marketing"
    assert company.classification_source == "BSE"


def test_dual_listed_company_has_two_listings(db_session):
    company = _company(isin="INE002A01018")
    db_session.add(company)
    db_session.commit()
    db_session.add(Listing(
        company_id=company.id, exchange="NSE", symbol="RELIANCE",
        series="EQ", status="ACTIVE", is_sme=False, is_primary=True,
        source="NSE", as_of=date(2026, 8, 3),
    ))
    db_session.add(Listing(
        company_id=company.id, exchange="BSE", symbol="RELIANCE",
        scrip_code="500325", group_code="A", status="ACTIVE", is_sme=False,
        is_primary=False, source="BSE", as_of=date(2026, 8, 3),
    ))
    db_session.commit()
    assert len(company.listings) == 2
    assert {l.exchange for l in company.listings} == {"NSE", "BSE"}


def test_alias_rows_attach_to_company(db_session):
    company = _company()
    db_session.add(company)
    db_session.commit()
    db_session.add(CompanyAlias(
        company_id=company.id, alias="Test Limited",
        alias_type="LEGAL", normalized="test",
    ))
    db_session.commit()
    assert db_session.query(CompanyAlias).one().normalized == "test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_universe_schema.py -v`
Expected: FAIL with `ImportError: cannot import name 'CompanyAlias' from 'app.models'`

- [ ] **Step 3: Add the columns and models**

In `app/models.py`, add `Boolean` and `Date` to the sqlalchemy import line, then add to `class Company` after `supply_chain_customers_json`:

```python
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
    # AMFI's PUBLISHED categorisation, when the list is available. Distinct
    # from the derived tier in app.market.cap_tier, which is computed on
    # read and never stored. NULL is normal and expected.
    amfi_tier = Column(String, nullable=True)  # LARGE | MID | SMALL
    amfi_rank = Column(Integer, nullable=True)
    amfi_as_of = Column(Date, nullable=True)
    tradeability = Column(
        String, nullable=False, default="NORMAL", server_default="NORMAL",
    )  # NORMAL | RESTRICTED | SME | SUSPENDED

    listings = relationship("Listing", back_populates="company")
    aliases = relationship("CompanyAlias", back_populates="company")
```

Then add both new models after `CompanyIndexMembership`:

```python
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
```

- [ ] **Step 4: Register the added columns for migration**

Append to `_ADDED_COLUMNS` in `app/db.py`, at the end of the list:

```python
    ("companies", "market", "VARCHAR NOT NULL DEFAULT 'INDIA'"),
    ("companies", "official_sector", "VARCHAR"),
    ("companies", "official_industry", "VARCHAR"),
    ("companies", "official_igroup", "VARCHAR"),
    ("companies", "official_isubgroup", "VARCHAR"),
    ("companies", "classification_source", "VARCHAR"),
    ("companies", "classification_as_of", "DATE"),
    ("companies", "market_cap_source", "VARCHAR"),
    ("companies", "market_cap_as_of", "DATE"),
    ("companies", "amfi_tier", "VARCHAR"),
    ("companies", "amfi_rank", "INTEGER"),
    ("companies", "amfi_as_of", "DATE"),
    ("companies", "tradeability", "VARCHAR NOT NULL DEFAULT 'NORMAL'"),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_universe_schema.py -v`
Expected: 4 passed

- [ ] **Step 6: Verify no existing test regressed**

Run: `python -m pytest -q`
Expected: same pass count as before this task, no new failures.

- [ ] **Step 7: Verify the migration applies to the real dev DB**

Run: `python -c "from app.db import init_db; init_db(); print('ok')"`
Then: `python -c "import sqlite3; print([r[1] for r in sqlite3.connect('newsflo.db').execute('PRAGMA table_info(companies)')])"`
Expected: prints `ok`, then a column list including `market`, `tradeability`, `amfi_tier`.

- [ ] **Step 8: Commit**

```bash
git add app/models.py app/db.py tests/test_universe_schema.py
git commit -m "feat: add universe provenance columns, listings and company_aliases tables"
```

---

# Phase 2 — Snapshot and Fetch

### Task 2: Snapshot layout and resume state

**Files:**
- Create: `app/companies/universe/__init__.py` (empty)
- Create: `app/companies/universe/snapshot.py`
- Test: `tests/test_universe_snapshot.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `snapshot_dir(root: str, day: date) -> Path`, `master_path(root, day, name: str) -> Path`, `detail_path(root, day, scrip_code: str) -> Path`, `fetched_scrip_codes(root, day) -> set[str]`, `latest_snapshot_day(root) -> date | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_universe_snapshot.py`:

```python
from datetime import date

from app.companies.universe import snapshot


def test_snapshot_dir_is_dated(tmp_path):
    path = snapshot.snapshot_dir(str(tmp_path), date(2026, 8, 3))
    assert path.name == "2026-08-03"


def test_master_and_detail_paths_are_separated(tmp_path):
    day = date(2026, 8, 3)
    master = snapshot.master_path(str(tmp_path), day, "nse_equity_l.csv")
    detail = snapshot.detail_path(str(tmp_path), day, "500325")
    assert master.name == "nse_equity_l.csv"
    assert detail.parent.name == "bse_detail"
    assert detail.name == "500325.json"


def test_fetched_scrip_codes_is_empty_before_any_fetch(tmp_path):
    assert snapshot.fetched_scrip_codes(str(tmp_path), date(2026, 8, 3)) == set()


def test_fetched_scrip_codes_reports_what_is_on_disk(tmp_path):
    day = date(2026, 8, 3)
    path = snapshot.detail_path(str(tmp_path), day, "500325")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    assert snapshot.fetched_scrip_codes(str(tmp_path), day) == {"500325"}


def test_latest_snapshot_day_picks_the_newest(tmp_path):
    for name in ("2026-07-01", "2026-08-03", "2026-06-15"):
        (tmp_path / name).mkdir()
    assert snapshot.latest_snapshot_day(str(tmp_path)) == date(2026, 8, 3)


def test_latest_snapshot_day_is_none_when_empty(tmp_path):
    assert snapshot.latest_snapshot_day(str(tmp_path)) is None


def test_latest_snapshot_day_ignores_non_date_directories(tmp_path):
    (tmp_path / "scratch").mkdir()
    (tmp_path / "2026-08-03").mkdir()
    assert snapshot.latest_snapshot_day(str(tmp_path)) == date(2026, 8, 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_universe_snapshot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.universe'`

- [ ] **Step 3: Implement**

Create `app/companies/universe/__init__.py` as an empty file. Create `app/companies/universe/snapshot.py`:

```python
"""Snapshot layout for the universe ingest (spec §4). Stage 1 (fetchers)
writes raw source responses here verbatim; stage 2 (normalize + loader)
reads only from here. That split is what makes the loader testable with no
network and replayable against any past day.

Pure path/filesystem logic -- no network, no DB, no app.models import.
"""
from datetime import date
from pathlib import Path

DEFAULT_ROOT = "data/universe"
DETAIL_DIRNAME = "bse_detail"


def snapshot_dir(root: str, day: date) -> Path:
    return Path(root) / day.isoformat()


def master_path(root: str, day: date, name: str) -> Path:
    return snapshot_dir(root, day) / name


def detail_path(root: str, day: date, scrip_code: str) -> Path:
    return snapshot_dir(root, day) / DETAIL_DIRNAME / f"{scrip_code}.json"


def fetched_scrip_codes(root: str, day: date) -> set[str]:
    """Scrip codes already on disk for ``day``. The resume set: a rerun
    skips these, so a rate-limit at scrip 3,000 costs the remaining 2,000
    rather than the whole run."""
    directory = snapshot_dir(root, day) / DETAIL_DIRNAME
    if not directory.is_dir():
        return set()
    return {p.stem for p in directory.glob("*.json")}


def latest_snapshot_day(root: str) -> date | None:
    """Newest snapshot day present, or None. Directories whose names aren't
    ISO dates are ignored rather than raising -- the root may hold scratch
    dirs."""
    base = Path(root)
    if not base.is_dir():
        return None
    days = []
    for child in base.iterdir():
        if not child.is_dir():
            continue
        try:
            days.append(date.fromisoformat(child.name))
        except ValueError:
            continue
    return max(days) if days else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_universe_snapshot.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/companies/universe/__init__.py app/companies/universe/snapshot.py tests/test_universe_snapshot.py
git commit -m "feat: snapshot layout and resume state for universe ingest"
```

---

### Task 3: Master-file fetchers (NSE equity list, BSE scrip list)

**Files:**
- Create: `app/companies/universe/fetchers.py`
- Test: `tests/test_universe_fetchers.py`

**Interfaces:**
- Consumes: `snapshot.master_path`, `snapshot.snapshot_dir`.
- Produces: `fetch_bytes(url: str, opener=...) -> bytes`, `fetch_nse_equity_list(root, day, opener=None) -> Path`, `fetch_bse_scrip_list(root, day, opener=None) -> Path`, constants `NSE_EQUITY_L_URL`, `BSE_SCRIP_LIST_URL`, `BSE_DETAIL_URL_TEMPLATE`, `BROWSER_HEADERS`.

Both exchanges reject non-browser User-Agents; BSE additionally requires a `Referer`. Verified working 2026-08-03.

- [ ] **Step 1: Write the failing test**

Create `tests/test_universe_fetchers.py`:

```python
from datetime import date

import pytest

from app.companies.universe import fetchers


class FakeOpener:
    """Stands in for the urllib opener. Records URLs, returns canned bytes."""

    def __init__(self, payloads):
        self.payloads = payloads
        self.urls = []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        if isinstance(self.payloads, Exception):
            raise self.payloads
        return self.payloads


def test_fetch_nse_equity_list_writes_snapshot(tmp_path):
    opener = FakeOpener(b"SYMBOL,NAME OF COMPANY\nRELIANCE,Reliance Industries Ltd\n")
    path = fetchers.fetch_nse_equity_list(str(tmp_path), date(2026, 8, 3), opener=opener)
    assert path.read_bytes().startswith(b"SYMBOL,")
    assert opener.urls == [fetchers.NSE_EQUITY_L_URL]


def test_fetch_bse_scrip_list_writes_snapshot(tmp_path):
    opener = FakeOpener(b'[{"SCRIP_CD":"500325"}]')
    path = fetchers.fetch_bse_scrip_list(str(tmp_path), date(2026, 8, 3), opener=opener)
    assert path.name == "bse_scrips.json"
    assert b"500325" in path.read_bytes()


def test_fetcher_propagates_failure_loudly(tmp_path):
    opener = FakeOpener(OSError("connection reset"))
    with pytest.raises(OSError):
        fetchers.fetch_nse_equity_list(str(tmp_path), date(2026, 8, 3), opener=opener)


def test_empty_response_is_rejected_before_writing(tmp_path):
    opener = FakeOpener(b"")
    with pytest.raises(ValueError):
        fetchers.fetch_nse_equity_list(str(tmp_path), date(2026, 8, 3), opener=opener)
    assert not fetchers.snapshot.master_path(
        str(tmp_path), date(2026, 8, 3), "nse_equity_l.csv"
    ).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_universe_fetchers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.universe.fetchers'`

- [ ] **Step 3: Implement**

Create `app/companies/universe/fetchers.py`:

```python
"""Stage 1 of the universe ingest: network only. Writes raw source
responses verbatim into a dated snapshot dir and returns the path. Nothing
here touches the DB or interprets a payload beyond an emptiness check.

Unlike the rest of the market plumbing, these fetchers RAISE on failure
rather than degrading. A source that changed shape or went away must fail
loudly at stage 1, before anything reaches the database -- silently loading
a truncated snapshot would corrupt the universe (spec §10).

Both exchanges reject non-browser User-Agents; BSE additionally requires a
Referer header. Verified against live endpoints on 2026-08-03.
"""
import ssl
import urllib.request
from datetime import date
from pathlib import Path

import certifi

from app.companies.universe import snapshot

NSE_EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_SCRIP_LIST_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
    "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
)
BSE_DETAIL_URL_TEMPLATE = (
    "https://api.bseindia.com/BseIndiaAPI/api/ComHeadernew/w"
    "?quotetype=EQ&scripcode={scrip_code}&seriesid="
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/csv, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
}


def fetch_bytes(url: str, timeout: int = 60) -> bytes:
    """Default transport. Tests inject a fake opener instead of calling
    this. certifi is required -- see CLAUDE.md on bare
    ssl.create_default_context failing without a CA bundle."""
    request = urllib.request.Request(url, headers=BROWSER_HEADERS)
    context = ssl.create_default_context(cafile=certifi.where())
    return urllib.request.urlopen(request, timeout=timeout, context=context).read()


def _write_master(root: str, day: date, name: str, payload: bytes) -> Path:
    if not payload:
        raise ValueError(f"empty payload for {name}; refusing to write snapshot")
    path = snapshot.master_path(root, day, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def fetch_nse_equity_list(root: str, day: date, opener=None) -> Path:
    fetch = opener or fetch_bytes
    return _write_master(root, day, "nse_equity_l.csv", fetch(NSE_EQUITY_L_URL))


def fetch_bse_scrip_list(root: str, day: date, opener=None) -> Path:
    fetch = opener or fetch_bytes
    return _write_master(root, day, "bse_scrips.json", fetch(BSE_SCRIP_LIST_URL))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_universe_fetchers.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/companies/universe/fetchers.py tests/test_universe_fetchers.py
git commit -m "feat: master-file fetchers for NSE equity list and BSE scrip list"
```

---

### Task 4: Resumable per-scrip detail fetcher

**Files:**
- Modify: `app/companies/universe/fetchers.py`
- Test: `tests/test_universe_fetchers.py`

**Interfaces:**
- Consumes: `snapshot.detail_path`, `snapshot.fetched_scrip_codes`, `BSE_DETAIL_URL_TEMPLATE`.
- Produces: `fetch_bse_details(root, day, scrip_codes: list[str], opener=None, sleep=None, throttle_seconds: float = 0.3, max_retries: int = 3) -> dict` returning `{"fetched": int, "skipped": int, "failed": list[str]}`.

~5,000 calls per full run. Must skip what's on disk, throttle, back off, and stop cleanly rather than hammering a rate-limiting endpoint.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_universe_fetchers.py`:

```python
class ScriptedOpener:
    """Returns a queued response per call; an Exception instance in the
    queue is raised instead of returned."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_fetch_bse_details_writes_one_file_per_scrip(tmp_path):
    opener = ScriptedOpener([b'{"ISIN":"INE002A01018"}', b'{"ISIN":"INE009A01021"}'])
    result = fetchers.fetch_bse_details(
        str(tmp_path), date(2026, 8, 3), ["500325", "500209"],
        opener=opener, sleep=lambda _s: None,
    )
    assert result["fetched"] == 2
    assert result["failed"] == []
    assert fetchers.snapshot.detail_path(str(tmp_path), date(2026, 8, 3), "500325").exists()


def test_fetch_bse_details_skips_codes_already_on_disk(tmp_path):
    day = date(2026, 8, 3)
    existing = fetchers.snapshot.detail_path(str(tmp_path), day, "500325")
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text('{"ISIN":"cached"}', encoding="utf-8")

    opener = ScriptedOpener([b'{"ISIN":"INE009A01021"}'])
    result = fetchers.fetch_bse_details(
        str(tmp_path), day, ["500325", "500209"], opener=opener, sleep=lambda _s: None,
    )
    assert result["skipped"] == 1
    assert result["fetched"] == 1
    assert existing.read_text(encoding="utf-8") == '{"ISIN":"cached"}'


def test_fetch_bse_details_retries_then_records_failure(tmp_path):
    opener = ScriptedOpener([OSError("429"), OSError("429"), OSError("429")])
    result = fetchers.fetch_bse_details(
        str(tmp_path), date(2026, 8, 3), ["500325"],
        opener=opener, sleep=lambda _s: None, max_retries=3,
    )
    assert result["failed"] == ["500325"]
    assert result["fetched"] == 0
    assert len(opener.urls) == 3


def test_fetch_bse_details_backs_off_between_retries(tmp_path):
    delays = []
    opener = ScriptedOpener([OSError("429"), b'{"ISIN":"INE002A01018"}'])
    fetchers.fetch_bse_details(
        str(tmp_path), date(2026, 8, 3), ["500325"],
        opener=opener, sleep=delays.append, max_retries=3, throttle_seconds=0.0,
    )
    assert delays and delays[0] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_universe_fetchers.py -k details -v`
Expected: FAIL with `AttributeError: module 'app.companies.universe.fetchers' has no attribute 'fetch_bse_details'`

- [ ] **Step 3: Implement**

Append to `app/companies/universe/fetchers.py`:

```python
import time

_BACKOFF_BASE_SECONDS = 2.0


def fetch_bse_details(
    root: str,
    day: date,
    scrip_codes: list[str],
    opener=None,
    sleep=None,
    throttle_seconds: float = 0.3,
    max_retries: int = 3,
) -> dict:
    """Fetch the official 4-level classification for each scrip, one call
    each (~5,000 for a full run). Resumable: codes already on disk for
    ``day`` are skipped, so a rate-limit partway through costs only the
    remainder.

    Unlike the master fetchers, a per-scrip failure does NOT raise -- one
    dead scrip must not cost the other 4,999. The code is recorded in
    ``failed`` and its company is later ingested with NULL classification
    rather than a guessed sector.
    """
    fetch = opener or fetch_bytes
    pause = sleep if sleep is not None else time.sleep
    already = snapshot.fetched_scrip_codes(root, day)

    fetched = 0
    skipped = 0
    failed: list[str] = []

    for scrip_code in scrip_codes:
        if scrip_code in already:
            skipped += 1
            continue

        payload = None
        for attempt in range(max_retries):
            try:
                payload = fetch(BSE_DETAIL_URL_TEMPLATE.format(scrip_code=scrip_code))
                break
            except Exception:
                if attempt == max_retries - 1:
                    break
                pause(_BACKOFF_BASE_SECONDS * (2 ** attempt))

        if not payload:
            failed.append(scrip_code)
            continue

        path = snapshot.detail_path(root, day, scrip_code)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        fetched += 1
        if throttle_seconds:
            pause(throttle_seconds)

    return {"fetched": fetched, "skipped": skipped, "failed": failed}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_universe_fetchers.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add app/companies/universe/fetchers.py tests/test_universe_fetchers.py
git commit -m "feat: resumable throttled BSE per-scrip detail fetcher"
```

---

# Phase 3 — Normalize (Pure)

### Task 5: Sector mapping and tradeability derivation

**Files:**
- Create: `app/companies/universe/sector_map.py`
- Test: `tests/test_universe_sector_map.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `OFFICIAL_SECTOR_TO_BUCKET: dict[str, str]`, `map_sector(official_sector: str | None) -> str`, `derive_tradeability(listings: list[dict]) -> str`, `listing_tradeability(exchange, series, group_code, status) -> str`.

The 12-value bucket vocabulary is fixed by existing consumers (`sector_indices.benchmark_ticker_for_sector`, `sub_sectors.SUB_SECTOR_TAXONOMY`, `ripple_templates`). BSE's `Sector` values are the SEBI macro-economic sector set.

- [ ] **Step 1: Write the failing test**

Create `tests/test_universe_sector_map.py`:

```python
import pytest

from app.companies.universe import sector_map


@pytest.mark.parametrize("official,expected", [
    ("Energy", "oil_gas"),
    ("Financial Services", "banking"),
    ("Information Technology", "it"),
    ("Healthcare", "pharma"),
    ("Fast Moving Consumer Goods", "fmcg"),
    ("Metals & Mining", "metals"),
    ("Telecommunication", "telecom"),
    ("Automobile and Auto Components", "auto"),
    ("Chemicals", "chemicals"),
    ("Construction", "infra"),
    ("Capital Goods", "infra"),
])
def test_official_sectors_map_to_closed_vocabulary(official, expected):
    assert sector_map.map_sector(official) == expected


def test_unknown_official_sector_falls_back_to_other():
    assert sector_map.map_sector("Something Unheard Of") == "other"


def test_missing_official_sector_falls_back_to_other():
    assert sector_map.map_sector(None) == "other"


def test_mapping_is_case_and_whitespace_insensitive():
    assert sector_map.map_sector("  energy  ") == "oil_gas"


def test_every_mapped_bucket_is_in_the_closed_vocabulary():
    allowed = {
        "banking", "fmcg", "pharma", "it", "oil_gas", "metals", "infra",
        "auto", "telecom", "chemicals", "defense", "railways_transport", "other",
    }
    assert set(sector_map.OFFICIAL_SECTOR_TO_BUCKET.values()) <= allowed


@pytest.mark.parametrize("exchange,series,group,expected", [
    ("NSE", "EQ", None, "NORMAL"),
    ("NSE", "BE", None, "RESTRICTED"),
    ("NSE", "BZ", None, "RESTRICTED"),
    ("BSE", None, "A", "NORMAL"),
    ("BSE", None, "B", "NORMAL"),
    ("BSE", None, "X", "RESTRICTED"),
    ("BSE", None, "XT", "RESTRICTED"),
    ("BSE", None, "T", "RESTRICTED"),
    ("BSE", None, "M", "SME"),
    ("BSE", None, "MT", "SME"),
    ("BSE", None, "Z", "SUSPENDED"),
])
def test_listing_tradeability(exchange, series, group, expected):
    assert sector_map.listing_tradeability(exchange, series, group, "ACTIVE") == expected


def test_suspended_status_overrides_group():
    assert sector_map.listing_tradeability("BSE", None, "A", "SUSPENDED") == "SUSPENDED"


def test_most_permissive_listing_wins():
    listings = [
        {"exchange": "NSE", "series": "EQ", "group_code": None, "status": "ACTIVE"},
        {"exchange": "BSE", "series": None, "group_code": "Z", "status": "ACTIVE"},
    ]
    assert sector_map.derive_tradeability(listings) == "NORMAL"


def test_company_with_only_a_suspended_listing_is_suspended():
    listings = [{"exchange": "BSE", "series": None, "group_code": "Z", "status": "ACTIVE"}]
    assert sector_map.derive_tradeability(listings) == "SUSPENDED"


def test_no_listings_defaults_to_normal():
    assert sector_map.derive_tradeability([]) == "NORMAL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_universe_sector_map.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.universe.sector_map'`

- [ ] **Step 3: Implement**

Create `app/companies/universe/sector_map.py`:

```python
"""Official BSE classification -> the app's 12-value closed sector
vocabulary, plus tradeability derivation (spec §5.2, §6).

This module REPLACES the keyword guessing in app.companies.loader's
SECTOR_MAP. That approach bucketed Coal India into oil_gas because its
combined NSE industry string contained "gas" (see loader.py's comment).
Mapping from a discrete official Sector value instead of substring-matching
a free-text industry string removes that entire class of bug.

Pure data + pure functions: no I/O, no DB, no app.models import.
"""

# Keys are BSE's `Sector` field (the SEBI macro-economic sector set),
# lowercased. Values are the app's closed vocabulary -- the same 12 used by
# app.market.sector_indices, app.companies.sub_sectors and
# app.market.ripple_templates. Unmapped -> "other", never a guess.
OFFICIAL_SECTOR_TO_BUCKET = {
    "energy": "oil_gas",
    "oil gas & consumable fuels": "oil_gas",
    "financial services": "banking",
    "information technology": "it",
    "healthcare": "pharma",
    "fast moving consumer goods": "fmcg",
    "consumer durables": "fmcg",
    "consumer services": "fmcg",
    "metals & mining": "metals",
    "telecommunication": "telecom",
    "automobile and auto components": "auto",
    "chemicals": "chemicals",
    "construction": "infra",
    "construction materials": "infra",
    "capital goods": "infra",
    "power": "infra",
    "utilities": "infra",
    "realty": "infra",
    "services": "other",
    "textiles": "other",
    "media entertainment & publication": "other",
    "forest materials": "other",
    "diversified": "other",
}

_NSE_NORMAL_SERIES = {"EQ"}
_BSE_NORMAL_GROUPS = {"A", "B"}
_BSE_SME_GROUPS = {"M", "MT", "MS"}
_BSE_SUSPENDED_GROUPS = {"Z", "ZP"}

# Ordered most- to least-permissive. derive_tradeability picks the best
# listing: a company that is EQ on NSE is normally tradeable even if its
# BSE listing sits in group Z.
_PERMISSIVENESS = ["NORMAL", "RESTRICTED", "SME", "SUSPENDED"]


def map_sector(official_sector: str | None) -> str:
    if not official_sector:
        return "other"
    return OFFICIAL_SECTOR_TO_BUCKET.get(official_sector.strip().lower(), "other")


def listing_tradeability(
    exchange: str, series: str | None, group_code: str | None, status: str | None,
) -> str:
    if (status or "").upper() == "SUSPENDED":
        return "SUSPENDED"
    if exchange == "NSE":
        return "NORMAL" if (series or "").upper() in _NSE_NORMAL_SERIES else "RESTRICTED"
    group = (group_code or "").upper()
    if group in _BSE_SUSPENDED_GROUPS:
        return "SUSPENDED"
    if group in _BSE_SME_GROUPS:
        return "SME"
    if group in _BSE_NORMAL_GROUPS:
        return "NORMAL"
    return "RESTRICTED"


def derive_tradeability(listings: list[dict]) -> str:
    """Most-permissive listing wins. A company with no listings (the
    curated market='GLOBAL' rows) is NORMAL."""
    if not listings:
        return "NORMAL"
    values = [
        listing_tradeability(
            l["exchange"], l.get("series"), l.get("group_code"), l.get("status"),
        )
        for l in listings
    ]
    return min(values, key=_PERMISSIVENESS.index)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_universe_sector_map.py -v`
Expected: 22 passed

- [ ] **Step 5: Commit**

```bash
git add app/companies/universe/sector_map.py tests/test_universe_sector_map.py
git commit -m "feat: official sector mapping and tradeability derivation"
```

---

### Task 6: Snapshot normalization and ISIN merge

**Files:**
- Create: `app/companies/universe/normalize.py`
- Create: `tests/fixtures/universe/2026-08-03/nse_equity_l.csv`
- Create: `tests/fixtures/universe/2026-08-03/bse_scrips.json`
- Create: `tests/fixtures/universe/2026-08-03/bse_detail/500325.json`
- Test: `tests/test_universe_normalize.py`

**Interfaces:**
- Consumes: `sector_map.map_sector`, `sector_map.derive_tradeability`.
- Produces: `is_company_isin(isin: str | None) -> bool`, `parse_nse_rows(csv_text: str) -> list[dict]`, `parse_bse_rows(json_text: str) -> list[dict]`, `parse_bse_detail(json_text: str) -> dict`, `build_records(nse_rows, bse_rows, details: dict[str, dict], as_of: date) -> list[dict]`. Each record: `{isin, name, sector, official_sector, official_industry, official_igroup, official_isubgroup, classification_source, classification_as_of, market_cap, market_cap_source, market_cap_as_of, tradeability, ticker, listings: list[dict]}`.

This is where dual-listing dedup happens. It is a pure function so the 2,278-company merge is testable without a database.

- [ ] **Step 1: Create the fixture snapshots**

Create `tests/fixtures/universe/2026-08-03/nse_equity_l.csv` — note the leading space in every header after the first, exactly as NSE publishes it:

```csv
SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10
NSEONLY,NSE Only Ltd,EQ,01-JAN-2010,10,1,INE999Z01011,10
SURVEIL,Surveillance Ltd,BE,01-JAN-2015,10,1,INE888Z01012,10
```

Create `tests/fixtures/universe/2026-08-03/bse_scrips.json`:

```json
[
  {"SCRIP_CD": "500325", "Scrip_Name": "Reliance Industries Ltd", "Status": "Active",
   "GROUP": "A", "FACE_VALUE": "10.00", "ISIN_NUMBER": "INE002A01018",
   "INDUSTRY": null, "scrip_id": "RELIANCE", "Segment": "Equity",
   "Issuer_Name": "Reliance Industries Limited", "Mktcap": "1750000.00"},
  {"SCRIP_CD": "543210", "Scrip_Name": "BSE Only Ltd", "Status": "Active",
   "GROUP": "X", "FACE_VALUE": "10.00", "ISIN_NUMBER": "INE777Z01013",
   "INDUSTRY": null, "scrip_id": "BSEONLY", "Segment": "Equity",
   "Issuer_Name": "BSE Only Limited", "Mktcap": "120.00"},
  {"SCRIP_CD": "590001", "Scrip_Name": "SME Co Ltd", "Status": "Active",
   "GROUP": "M", "FACE_VALUE": "10.00", "ISIN_NUMBER": "INE666Z01014",
   "INDUSTRY": null, "scrip_id": "SMECO", "Segment": "Equity",
   "Issuer_Name": "SME Co Limited", "Mktcap": ""},
  {"SCRIP_CD": "999999", "Scrip_Name": "Some ETF Units", "Status": "Active",
   "GROUP": "B", "FACE_VALUE": "10.00", "ISIN_NUMBER": "INF204KB14I5",
   "INDUSTRY": null, "scrip_id": "SOMEETF", "Segment": "Equity",
   "Issuer_Name": "Some ETF", "Mktcap": "500.00"}
]
```

Create `tests/fixtures/universe/2026-08-03/bse_detail/500325.json`:

```json
{"SecurityId": "RELIANCE", "SecurityCode": "500325", "ISIN": "INE002A01018",
 "Industry": "Refineries & Marketing", "Group": "A", "Sector": "Energy",
 "IndustryNew": "Oil, Gas & Consumable Fuels", "IGroup": "Petroleum Products",
 "ISubGroup": "Refineries & Marketing"}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_universe_normalize.py`:

```python
import json
from datetime import date
from pathlib import Path

from app.companies.universe import normalize

FIXTURES = Path(__file__).parent / "fixtures" / "universe" / "2026-08-03"
AS_OF = date(2026, 8, 3)


def _load():
    nse = normalize.parse_nse_rows((FIXTURES / "nse_equity_l.csv").read_text(encoding="utf-8"))
    bse = normalize.parse_bse_rows((FIXTURES / "bse_scrips.json").read_text(encoding="utf-8"))
    details = {
        p.stem: normalize.parse_bse_detail(p.read_text(encoding="utf-8"))
        for p in (FIXTURES / "bse_detail").glob("*.json")
    }
    return normalize.build_records(nse, bse, details, AS_OF)


def test_inclusion_rule_accepts_equity_isins():
    assert normalize.is_company_isin("INE002A01018") is True
    assert normalize.is_company_isin("IN9002A01018") is True


def test_inclusion_rule_rejects_fund_units_and_junk():
    assert normalize.is_company_isin("INF204KB14I5") is False
    assert normalize.is_company_isin("NA") is False
    assert normalize.is_company_isin("") is False
    assert normalize.is_company_isin(None) is False


def test_etf_units_are_excluded_from_records():
    isins = {r["isin"] for r in _load()}
    assert "INF204KB14I5" not in isins


def test_dual_listed_company_appears_exactly_once():
    records = [r for r in _load() if r["isin"] == "INE002A01018"]
    assert len(records) == 1
    assert len(records[0]["listings"]) == 2


def test_dual_listed_primary_ticker_prefers_nse():
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    assert record["ticker"] == "RELIANCE.NS"
    primary = [l for l in record["listings"] if l["is_primary"]]
    assert len(primary) == 1 and primary[0]["exchange"] == "NSE"


def test_bse_only_company_gets_bo_ticker():
    record = next(r for r in _load() if r["isin"] == "INE777Z01013")
    assert record["ticker"] == "BSEONLY.BO"
    assert record["tradeability"] == "RESTRICTED"


def test_nse_only_company_gets_ns_ticker_and_no_classification():
    record = next(r for r in _load() if r["isin"] == "INE999Z01011")
    assert record["ticker"] == "NSEONLY.NS"
    assert record["official_sector"] is None
    assert record["classification_source"] is None
    assert record["sector"] == "other"


def test_official_classification_is_stored_verbatim():
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    assert record["official_sector"] == "Energy"
    assert record["official_isubgroup"] == "Refineries & Marketing"
    assert record["classification_source"] == "BSE"
    assert record["classification_as_of"] == AS_OF
    assert record["sector"] == "oil_gas"


def test_market_cap_comes_from_bse_with_provenance():
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    assert record["market_cap"] == 1750000.0
    assert record["market_cap_source"] == "BSE"
    assert record["market_cap_as_of"] == AS_OF


def test_blank_market_cap_is_null_not_zero():
    record = next(r for r in _load() if r["isin"] == "INE666Z01014")
    assert record["market_cap"] is None
    assert record["market_cap_source"] is None


def test_sme_group_marks_listing_and_company():
    record = next(r for r in _load() if r["isin"] == "INE666Z01014")
    assert record["tradeability"] == "SME"
    assert record["listings"][0]["is_sme"] is True


def test_nse_be_series_is_restricted():
    record = next(r for r in _load() if r["isin"] == "INE888Z01012")
    assert record["tradeability"] == "RESTRICTED"


def test_legal_name_prefers_bse_issuer_name():
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    assert record["name"] == "Reliance Industries Limited"


def test_listing_carries_source_and_as_of():
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    for listing in record["listings"]:
        assert listing["as_of"] == AS_OF
        assert listing["source"] in ("NSE", "BSE")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_universe_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.universe.normalize'`

- [ ] **Step 4: Implement**

Create `app/companies/universe/normalize.py`:

```python
"""Stage 2a of the universe ingest: pure transforms from raw snapshot text
to canonical company records. No network, no DB, no app.models import --
which is what lets the 2,278-company dual-listing merge be tested with
plain dicts.

The ISIN is the identity key. NSE and BSE rows for the same ISIN collapse
into ONE record with TWO listings; keying on ticker instead would duplicate
46% of the universe (spec §1).
"""
import csv
import io
import json
from datetime import date

from app.companies.universe import sector_map

# Equity ISIN prefixes. INF* are mutual-fund/ETF units (253 on BSE) and are
# not companies; BSE also publishes one row whose ISIN is the literal "NA".
# This predicate is what reduces the 5,220-ISIN union to ~4,967 companies.
_COMPANY_ISIN_PREFIXES = ("INE", "IN9")


def is_company_isin(isin: str | None) -> bool:
    if not isin:
        return False
    return isin.strip().upper().startswith(_COMPANY_ISIN_PREFIXES)


def _clean(value) -> str:
    return (value or "").strip() if isinstance(value, str) else ""


def parse_nse_rows(csv_text: str) -> list[dict]:
    """NSE publishes EQUITY_L.csv with a leading space in every header
    after the first (" SERIES", " ISIN NUMBER"). Strip keys and values."""
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []
    for raw in reader:
        row = {(k or "").strip(): _clean(v) for k, v in raw.items()}
        if is_company_isin(row.get("ISIN NUMBER")):
            rows.append(row)
    return rows


def parse_bse_rows(json_text: str) -> list[dict]:
    rows = []
    for raw in json.loads(json_text):
        row = {k: (v if v is not None else "") for k, v in raw.items()}
        if is_company_isin(_clean(row.get("ISIN_NUMBER"))):
            rows.append(row)
    return rows


def parse_bse_detail(json_text: str) -> dict:
    payload = json.loads(json_text)
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    return payload or {}


def _parse_float(value) -> float | None:
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _parse_nse_date(value: str) -> date | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return date(
            int(text[7:11]),
            ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
             "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"].index(text[3:6].upper()) + 1,
            int(text[0:2]),
        )
    except (ValueError, IndexError):
        return None


def build_records(
    nse_rows: list[dict], bse_rows: list[dict], details: dict[str, dict], as_of: date,
) -> list[dict]:
    """Merge both exchange masters by ISIN into canonical records.

    ``details`` is {scrip_code: parsed detail payload}. A scrip whose detail
    is absent yields NULL classification and NULL classification_source --
    never a guessed sector (spec §4).
    """
    merged: dict[str, dict] = {}

    for row in nse_rows:
        isin = row["ISIN NUMBER"].strip().upper()
        record = merged.setdefault(isin, _blank_record(isin, as_of))
        record["nse_name"] = row.get("NAME OF COMPANY", "")
        record["listings"].append({
            "exchange": "NSE",
            "symbol": row["SYMBOL"],
            "scrip_code": None,
            "series": row.get("SERIES") or None,
            "group_code": None,
            "status": "ACTIVE",
            "is_sme": False,
            "is_primary": False,
            "face_value": _parse_float(row.get("FACE VALUE")),
            "listed_on": _parse_nse_date(row.get("DATE OF LISTING", "")),
            "source": "NSE",
            "as_of": as_of,
        })

    for row in bse_rows:
        isin = _clean(row.get("ISIN_NUMBER")).upper()
        record = merged.setdefault(isin, _blank_record(isin, as_of))
        scrip_code = _clean(row.get("SCRIP_CD"))
        group_code = _clean(row.get("GROUP")).upper() or None
        record["bse_name"] = _clean(row.get("Issuer_Name")) or _clean(row.get("Scrip_Name"))

        market_cap = _parse_float(row.get("Mktcap"))
        if market_cap is not None:
            record["market_cap"] = market_cap
            record["market_cap_source"] = "BSE"
            record["market_cap_as_of"] = as_of

        detail = details.get(scrip_code)
        if detail:
            record["official_sector"] = _clean(detail.get("Sector")) or None
            record["official_industry"] = _clean(detail.get("IndustryNew")) or None
            record["official_igroup"] = _clean(detail.get("IGroup")) or None
            record["official_isubgroup"] = _clean(detail.get("ISubGroup")) or None
            if record["official_sector"]:
                record["classification_source"] = "BSE"
                record["classification_as_of"] = as_of

        record["listings"].append({
            "exchange": "BSE",
            "symbol": _clean(row.get("scrip_id")) or scrip_code,
            "scrip_code": scrip_code,
            "series": None,
            "group_code": group_code,
            "status": "SUSPENDED" if _clean(row.get("Status")).upper() == "SUSPENDED" else "ACTIVE",
            "is_sme": group_code in ("M", "MT", "MS"),
            "is_primary": False,
            "face_value": _parse_float(row.get("FACE_VALUE")),
            "listed_on": None,
            "source": "BSE",
            "as_of": as_of,
        })

    records = []
    for record in merged.values():
        nse_listing = next((l for l in record["listings"] if l["exchange"] == "NSE"), None)
        primary = nse_listing or record["listings"][0]
        primary["is_primary"] = True
        suffix = ".NS" if primary["exchange"] == "NSE" else ".BO"
        record["ticker"] = f"{primary['symbol']}{suffix}"
        # BSE's Issuer_Name is the registrar-style legal name and is the
        # better display/alias source; fall back to NSE's when BSE has no
        # listing for this ISIN.
        record["name"] = record.pop("bse_name", "") or record.pop("nse_name", "") or primary["symbol"]
        record.pop("nse_name", None)
        record["sector"] = sector_map.map_sector(record["official_sector"])
        record["tradeability"] = sector_map.derive_tradeability(record["listings"])
        records.append(record)
    return records


def _blank_record(isin: str, as_of: date) -> dict:
    return {
        "isin": isin,
        "name": "",
        "sector": "other",
        "official_sector": None,
        "official_industry": None,
        "official_igroup": None,
        "official_isubgroup": None,
        "classification_source": None,
        "classification_as_of": None,
        "market_cap": None,
        "market_cap_source": None,
        "market_cap_as_of": None,
        "tradeability": "NORMAL",
        "ticker": "",
        "listings": [],
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_universe_normalize.py -v`
Expected: 14 passed

- [ ] **Step 6: Commit**

```bash
git add app/companies/universe/normalize.py tests/test_universe_normalize.py tests/fixtures/universe
git commit -m "feat: snapshot normalization with ISIN merge for dual-listed companies"
```

---

# Phase 4 — Load

### Task 7: ISIN-keyed loader

**Files:**
- Create: `app/companies/universe/loader.py`
- Test: `tests/test_universe_loader.py`

**Interfaces:**
- Consumes: `normalize.build_records` output shape, models `Company`, `Listing`.
- Produces: `upsert_records(session, records: list[dict]) -> dict` returning `{"created": int, "updated": int, "listings": int, "skipped": list[str]}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_universe_loader.py`:

```python
from datetime import date

from app.companies.universe import loader
from app.models import Company, Listing

AS_OF = date(2026, 8, 3)


def _record(isin, ticker, name, **kw):
    record = {
        "isin": isin, "ticker": ticker, "name": name, "sector": "oil_gas",
        "official_sector": "Energy", "official_industry": "Oil, Gas & Consumable Fuels",
        "official_igroup": "Petroleum Products", "official_isubgroup": "Refineries & Marketing",
        "classification_source": "BSE", "classification_as_of": AS_OF,
        "market_cap": 1750000.0, "market_cap_source": "BSE", "market_cap_as_of": AS_OF,
        "tradeability": "NORMAL",
        "listings": [{
            "exchange": "NSE", "symbol": ticker.split(".")[0], "scrip_code": None,
            "series": "EQ", "group_code": None, "status": "ACTIVE", "is_sme": False,
            "is_primary": True, "face_value": 10.0, "listed_on": None,
            "source": "NSE", "as_of": AS_OF,
        }],
    }
    record.update(kw)
    return record


def test_creates_company_and_listing(db_session):
    result = loader.upsert_records(db_session, [_record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited")])
    assert result["created"] == 1
    company = db_session.query(Company).one()
    assert company.isin == "INE002A01018"
    assert company.market == "INDIA"
    assert company.official_isubgroup == "Refineries & Marketing"
    assert db_session.query(Listing).count() == 1


def test_rerun_updates_rather_than_duplicates(db_session):
    record = _record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited")
    loader.upsert_records(db_session, [record])
    result = loader.upsert_records(db_session, [record])
    assert result["created"] == 0
    assert result["updated"] == 1
    assert db_session.query(Company).count() == 1
    assert db_session.query(Listing).count() == 1


def test_matches_existing_company_by_isin_and_preserves_id(db_session):
    existing = Company(
        ticker="RELIANCE.NS", name="Reliance Industries Ltd.", sector="oil_gas",
        index_tier="NIFTY50", isin="INE002A01018",
    )
    db_session.add(existing)
    db_session.commit()
    original_id = existing.id

    loader.upsert_records(db_session, [_record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited")])
    company = db_session.query(Company).one()
    assert company.id == original_id
    assert company.index_tier == "NIFTY50"


def test_matches_existing_company_by_ticker_when_isin_missing(db_session):
    existing = Company(
        ticker="RELIANCE.NS", name="Reliance Industries Ltd.", sector="oil_gas",
        index_tier="NIFTY50",
    )
    db_session.add(existing)
    db_session.commit()

    loader.upsert_records(db_session, [_record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited")])
    assert db_session.query(Company).count() == 1
    assert db_session.query(Company).one().isin == "INE002A01018"


def test_absent_classification_writes_null_not_a_guess(db_session):
    record = _record(
        "INE999Z01011", "NSEONLY.NS", "NSE Only Limited",
        sector="other", official_sector=None, official_industry=None,
        official_igroup=None, official_isubgroup=None,
        classification_source=None, classification_as_of=None,
        market_cap=None, market_cap_source=None, market_cap_as_of=None,
    )
    loader.upsert_records(db_session, [record])
    company = db_session.query(Company).one()
    assert company.official_sector is None
    assert company.classification_source is None
    assert company.market_cap is None


def test_never_overwrites_exchange_cap_with_null(db_session):
    loader.upsert_records(db_session, [_record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited")])
    loader.upsert_records(db_session, [_record(
        "INE002A01018", "RELIANCE.NS", "Reliance Industries Limited",
        market_cap=None, market_cap_source=None, market_cap_as_of=None,
    )])
    assert db_session.query(Company).one().market_cap == 1750000.0


def test_absent_classification_never_clobbers_a_stored_one(db_session):
    # The daily master refresh runs with an empty bse_detail/ dir. It must
    # not null out classification written by the monthly detail pass.
    loader.upsert_records(db_session, [_record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited")])
    loader.upsert_records(db_session, [_record(
        "INE002A01018", "RELIANCE.NS", "Reliance Industries Limited",
        sector="other", official_sector=None, official_industry=None,
        official_igroup=None, official_isubgroup=None,
        classification_source=None, classification_as_of=None,
    )])
    company = db_session.query(Company).one()
    assert company.official_sector == "Energy"
    assert company.sector == "oil_gas"
    assert company.classification_source == "BSE"


def test_second_exchange_listing_is_added_not_duplicated(db_session):
    record = _record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited")
    loader.upsert_records(db_session, [record])
    record["listings"].append({
        "exchange": "BSE", "symbol": "RELIANCE", "scrip_code": "500325",
        "series": None, "group_code": "A", "status": "ACTIVE", "is_sme": False,
        "is_primary": False, "face_value": 10.0, "listed_on": None,
        "source": "BSE", "as_of": AS_OF,
    })
    loader.upsert_records(db_session, [record])
    assert db_session.query(Company).count() == 1
    assert db_session.query(Listing).count() == 2


def test_record_without_isin_is_skipped(db_session):
    result = loader.upsert_records(db_session, [_record("", "BROKEN.NS", "Broken Ltd")])
    assert result["skipped"] == ["BROKEN.NS"]
    assert db_session.query(Company).count() == 0


def test_ticker_collision_with_a_different_isin_is_skipped(db_session):
    db_session.add(Company(
        ticker="CLASH.NS", name="Existing Ltd", sector="other",
        index_tier="OTHER", isin="INE111Z01010",
    ))
    db_session.commit()
    result = loader.upsert_records(db_session, [_record("INE222Z01011", "CLASH.NS", "New Ltd")])
    assert result["skipped"] == ["CLASH.NS"]
    assert db_session.query(Company).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_universe_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.universe.loader'`

- [ ] **Step 3: Implement**

Create `app/companies/universe/loader.py`:

```python
"""Stage 2b of the universe ingest: the only module here that touches the
DB. Upserts canonical records by ISIN.

companies.id is NEVER reassigned -- it is FK'd by alert_companies,
user_watchlist_companies, holdings, market_moves, car_outcomes,
calibration_samples and impact_edges. An existing row is matched by ISIN
first, then by ticker (which is how the pre-ISIN 509 companies are adopted
without losing their alert history).
"""
from sqlalchemy.orm import Session

from app.models import Company, Listing

# Always refreshed from the masters -- cheap, fetched daily, always present.
_ALWAYS_FIELDS = ("name", "tradeability")
# Only refreshed when the snapshot actually carries a classification. The
# daily master refresh runs with an empty bse_detail/ dir (the detail pass
# is monthly), so writing these unconditionally would null out every
# company's classification once a day.
_CLASSIFICATION_FIELDS = (
    "sector", "official_sector", "official_industry", "official_igroup",
    "official_isubgroup", "classification_source", "classification_as_of",
)


def _find_existing(session: Session, record: dict) -> Company | None:
    company = session.query(Company).filter_by(isin=record["isin"]).one_or_none()
    if company is not None:
        return company
    return session.query(Company).filter_by(ticker=record["ticker"]).one_or_none()


def _sync_listings(session: Session, company: Company, listings: list[dict]) -> int:
    written = 0
    for entry in listings:
        existing = (
            session.query(Listing)
            .filter_by(company_id=company.id, exchange=entry["exchange"])
            .one_or_none()
        )
        if existing is None:
            existing = Listing(company_id=company.id, exchange=entry["exchange"])
            session.add(existing)
        for field in (
            "symbol", "scrip_code", "series", "group_code", "status",
            "is_sme", "is_primary", "face_value", "listed_on", "source", "as_of",
        ):
            setattr(existing, field, entry[field])
        written += 1
    return written


def upsert_records(session: Session, records: list[dict]) -> dict:
    """Create or update one Company (+ its Listings) per record.

    A record is skipped -- never guessed at -- when it has no ISIN, or when
    its ticker already belongs to a DIFFERENT ISIN. Skipping keeps the
    unique constraint intact and surfaces the conflict to the caller
    instead of silently rewriting an unrelated company.
    """
    created = updated = listings_written = 0
    skipped: list[str] = []

    for record in records:
        if not record.get("isin"):
            skipped.append(record.get("ticker") or "<no-ticker>")
            continue

        company = _find_existing(session, record)
        if company is not None and company.isin and company.isin != record["isin"]:
            skipped.append(record["ticker"])
            continue

        if company is None:
            company = Company(
                ticker=record["ticker"], name=record["name"], sector=record["sector"],
                index_tier="OTHER", market="INDIA", isin=record["isin"],
            )
            session.add(company)
            session.flush()  # assign company.id for the listing rows
            created += 1
        else:
            company.isin = record["isin"]
            company.ticker = record["ticker"]
            updated += 1

        for field in _ALWAYS_FIELDS:
            setattr(company, field, record[field])

        if record["classification_source"]:
            for field in _CLASSIFICATION_FIELDS:
                setattr(company, field, record[field])

        # A missing cap must never blank an exchange-published one (spec
        # §6.2) -- a stale real cap beats a nulled-out tier, same rule as
        # app.companies.market_caps.refresh_market_caps.
        if record["market_cap"] is not None:
            company.market_cap = record["market_cap"]
            company.market_cap_source = record["market_cap_source"]
            company.market_cap_as_of = record["market_cap_as_of"]

        listings_written += _sync_listings(session, company, record["listings"])
        session.commit()

    return {
        "created": created, "updated": updated,
        "listings": listings_written, "skipped": skipped,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_universe_loader.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add app/companies/universe/loader.py tests/test_universe_loader.py
git commit -m "feat: ISIN-keyed universe loader preserving company ids"
```

---

# Phase 5 — Matcher Rebuild

### Task 8: Company-name canonicalization

**Files:**
- Create: `app/companies/matching/__init__.py` (empty)
- Create: `app/companies/matching/normalize.py`
- Test: `tests/test_matching_normalize.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `normalize_name(raw: str | None) -> str`, `tokens(raw: str | None) -> frozenset[str]`, `LEGAL_SUFFIXES: tuple[str, ...]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_matching_normalize.py`:

```python
import pytest

from app.companies.matching import normalize


@pytest.mark.parametrize("raw,expected", [
    ("Reliance Industries Limited", "reliance industries"),
    ("Reliance Industries Ltd.", "reliance industries"),
    ("RELIANCE INDUSTRIES LTD", "reliance industries"),
    ("  Reliance   Industries  Ltd  ", "reliance industries"),
    ("Tata Consultancy Services Limited", "tata consultancy services"),
    ("Bajaj Finserv Ltd", "bajaj finserv"),
])
def test_legal_suffixes_are_stripped(raw, expected):
    assert normalize.normalize_name(raw) == expected


def test_ampersand_is_expanded():
    assert normalize.normalize_name("Procter & Gamble") == "procter and gamble"


def test_punctuation_is_removed():
    assert normalize.normalize_name("J.B. Chemicals") == "jb chemicals"


def test_india_is_never_stripped():
    # Stripping geography tokens manufactures collisions -- see spec 8.1.
    assert normalize.normalize_name("Apollo Hospitals") != normalize.normalize_name("Apollo Tyres")
    assert "india" in normalize.normalize_name("Oil India Limited")


def test_bharat_is_never_stripped():
    assert "bharat" in normalize.normalize_name("Bharat Gears Ltd")
    assert normalize.normalize_name("Bharat Gears Ltd") != normalize.normalize_name("Bharat Seats Ltd")


def test_suffix_only_stripped_at_the_end():
    # "Co" inside a name is a real word, not a suffix.
    assert normalize.normalize_name("Coal India Ltd") == "coal india"


def test_empty_and_none_are_safe():
    assert normalize.normalize_name(None) == ""
    assert normalize.normalize_name("   ") == ""


def test_multiple_trailing_suffixes_are_all_stripped():
    assert normalize.normalize_name("Some Name Pvt Ltd") == "some name"


def test_tokens_ignore_order():
    assert normalize.tokens("Reliance Industries Ltd") == normalize.tokens("Industries Reliance")


def test_tokens_of_empty_is_empty():
    assert normalize.tokens("") == frozenset()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_matching_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.matching'`

- [ ] **Step 3: Implement**

Create `app/companies/matching/__init__.py` as an empty file. Create `app/companies/matching/normalize.py`:

```python
"""Canonical form for company names. Pure -- no I/O, no DB.

Every rung of the match ladder compares normalized strings for EXACT
equality. The old resolver's substring matching (``name in c.name or
c.name in name``) is what produced silent mismatches, so nothing here
introduces partial matching.

Geography tokens ("india", "bharat") are deliberately NOT stripped: they
discriminate between genuinely different companies (Apollo Tyres vs Apollo
Hospitals, Bharat Gears vs Bharat Seats), and removing them manufactures
collisions the ladder would then have to resolve by guessing.
"""
import re

# End-anchored only. "Co" inside "Coal India" is a word, not a suffix.
LEGAL_SUFFIXES = (
    "limited", "ltd", "private", "pvt", "corporation", "corp",
    "company", "co", "incorporated", "inc", "plc",
)

# AMENDED 2026-08-03. The original single-regex version here contradicted this
# task's own test: sub(" ") turns "J.B. Chemicals" into "j b chemicals", not
# "jb chemicals". Checked against all 7,500 real NSE+BSE names — 98 carry an
# embedded dot, 114 an embedded hyphen — so one rule cannot serve both. Dots
# abbreviate a single word and must JOIN; every other mark separates two words
# and must SPLIT. Order matters: dots first.
_DOTS = re.compile(r"\.")
_OTHER_PUNCTUATION = re.compile(r"[^a-z0-9\s]")
_WHITESPACE = re.compile(r"\s+")


def normalize_name(raw: str | None) -> str:
    if not raw:
        return ""
    text = raw.strip().lower().replace("&", " and ")
    text = _DOTS.sub("", text)
    text = _OTHER_PUNCTUATION.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    if not text:
        return ""

    parts = text.split(" ")
    while len(parts) > 1 and parts[-1] in LEGAL_SUFFIXES:
        parts.pop()
    return " ".join(parts)


def tokens(raw: str | None) -> frozenset[str]:
    normalized = normalize_name(raw)
    return frozenset(normalized.split(" ")) if normalized else frozenset()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_matching_normalize.py -v`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add app/companies/matching/__init__.py app/companies/matching/normalize.py tests/test_matching_normalize.py
git commit -m "feat: company-name canonicalization for entity matching"
```

---

### Task 9: Alias building

**Files:**
- Create: `app/companies/matching/curated.py`
- Create: `app/companies/matching/aliases.py`
- Test: `tests/test_matching_aliases.py`

**Interfaces:**
- Consumes: `normalize.normalize_name`, models `Company`, `Listing`, `CompanyAlias`.
- Produces: `CURATED_TRADE_NAMES: dict[str, tuple[str, ...]]` (ticker → trade names), `build_aliases_for_company(company) -> list[dict]`, `rebuild_aliases(session) -> int`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_matching_aliases.py`:

```python
from datetime import date

from app.companies.matching import aliases
from app.models import Company, CompanyAlias, Listing


def _company(session, ticker="RELIANCE.NS", name="Reliance Industries Limited", **kw):
    company = Company(
        ticker=ticker, name=name, sector="oil_gas", index_tier="NIFTY50", **kw,
    )
    session.add(company)
    session.commit()
    return company


def test_legal_name_becomes_an_alias(db_session):
    company = _company(db_session)
    aliases.rebuild_aliases(db_session)
    normalized = {a.normalized for a in db_session.query(CompanyAlias).all()}
    assert "reliance industries" in normalized


def test_listing_symbols_become_aliases(db_session):
    company = _company(db_session)
    db_session.add(Listing(
        company_id=company.id, exchange="NSE", symbol="RELIANCE", series="EQ",
        status="ACTIVE", is_sme=False, is_primary=True, source="NSE", as_of=date(2026, 8, 3),
    ))
    db_session.commit()
    aliases.rebuild_aliases(db_session)
    rows = db_session.query(CompanyAlias).filter_by(alias_type="NSE_SYMBOL").all()
    assert [r.normalized for r in rows] == ["reliance"]


def test_curated_trade_names_are_added(db_session):
    _company(db_session, ticker="INFY.NS", name="Infosys Limited")
    aliases.rebuild_aliases(db_session)
    rows = db_session.query(CompanyAlias).filter_by(alias_type="TRADE_NAME").all()
    assert any(r.normalized == "infosys" for r in rows)


def test_rebuild_is_idempotent(db_session):
    _company(db_session)
    first = aliases.rebuild_aliases(db_session)
    second = aliases.rebuild_aliases(db_session)
    assert first == second
    assert db_session.query(CompanyAlias).count() == first


def test_duplicate_normalized_forms_collapse_to_one_row(db_session):
    # "Reliance Industries Ltd" and "Reliance Industries Limited" normalize
    # identically; only one alias row may exist per (normalized, company).
    company = _company(db_session)
    db_session.add(Listing(
        company_id=company.id, exchange="BSE", symbol="RELIANCE", scrip_code="500325",
        group_code="A", status="ACTIVE", is_sme=False, is_primary=False,
        source="BSE", as_of=date(2026, 8, 3),
    ))
    db_session.commit()
    aliases.rebuild_aliases(db_session)
    rows = db_session.query(CompanyAlias).filter_by(normalized="reliance").all()
    assert len(rows) == 1


def test_blank_normalized_forms_are_not_stored(db_session):
    _company(db_session, ticker="ODD.NS", name="!!!")
    aliases.rebuild_aliases(db_session)
    assert all(a.normalized for a in db_session.query(CompanyAlias).all())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_matching_aliases.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.matching.aliases'`

- [ ] **Step 3: Implement curated names**

Create `app/companies/matching/curated.py`:

```python
"""Trade names that no exchange registry carries.

Reviewed by hand, keyed by ticker. This file exists because registries hold
legal names ("Infosys Limited", "Life Insurance Corporation of India") while
news copy uses trade names ("Infosys", "LIC"). Keep it small and reviewed --
it is the one place in the matching package where a human asserts a fact
rather than deriving it from a source.
"""

CURATED_TRADE_NAMES: dict[str, tuple[str, ...]] = {
    "INFY.NS": ("Infosys",),
    "TCS.NS": ("TCS", "Tata Consultancy"),
    "LICI.NS": ("LIC", "Life Insurance Corporation"),
    "MARUTI.NS": ("Maruti", "Maruti Suzuki"),
    "HDFCBANK.NS": ("HDFC Bank",),
    "ICICIBANK.NS": ("ICICI Bank",),
    "SBIN.NS": ("SBI", "State Bank of India"),
    "RELIANCE.NS": ("Reliance", "RIL"),
    "BHARTIARTL.NS": ("Airtel", "Bharti Airtel"),
    "HINDUNILVR.NS": ("HUL", "Hindustan Unilever"),
    "LT.NS": ("L&T", "Larsen and Toubro"),
    "M&M.NS": ("Mahindra", "Mahindra and Mahindra"),
    "HINDPETRO.NS": ("HPCL", "Hindustan Petroleum"),
    "BPCL.NS": ("BPCL", "Bharat Petroleum"),
    "IOC.NS": ("IOC", "Indian Oil"),
    "OIL.NS": ("Oil India",),
}
```

- [ ] **Step 4: Implement alias building**

Create `app/companies/matching/aliases.py`:

```python
"""Builds the company_aliases rows the matcher looks up.

Every alias comes from ingest data (exchange registries, listing symbols)
or the reviewed curated.py file. No LLM is involved -- this is master data,
not per-event data, same discipline as app.companies.business_profile's
"one-time enrichment, never written by the analysis pipeline".
"""
from sqlalchemy.orm import Session

from app.companies.matching.curated import CURATED_TRADE_NAMES
from app.companies.matching.normalize import normalize_name
from app.models import Company, CompanyAlias


def build_aliases_for_company(company: Company) -> list[dict]:
    """All alias candidates for one company, deduplicated by normalized
    form. First writer of a normalized form wins, so the LEGAL name's type
    survives when a symbol happens to normalize identically."""
    candidates: list[tuple[str, str]] = [(company.name, "LEGAL")]

    for listing in company.listings:
        alias_type = "NSE_SYMBOL" if listing.exchange == "NSE" else "BSE_ID"
        candidates.append((listing.symbol, alias_type))

    for trade_name in CURATED_TRADE_NAMES.get(company.ticker, ()):
        candidates.append((trade_name, "TRADE_NAME"))

    seen: set[str] = set()
    rows = []
    for alias, alias_type in candidates:
        normalized = normalize_name(alias)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        rows.append({"alias": alias, "alias_type": alias_type, "normalized": normalized})
    return rows


def rebuild_aliases(session: Session) -> int:
    """Rebuild the alias set for every company. Idempotent: deletes this
    company's existing rows before rewriting, so a rerun after a name change
    doesn't leave a stale alias pointing at the wrong company. Returns the
    total row count."""
    total = 0
    for company in session.query(Company).all():
        session.query(CompanyAlias).filter_by(company_id=company.id).delete()
        for row in build_aliases_for_company(company):
            session.add(CompanyAlias(company_id=company.id, **row))
            total += 1
    session.commit()
    return total
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_matching_aliases.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add app/companies/matching/curated.py app/companies/matching/aliases.py tests/test_matching_aliases.py
git commit -m "feat: alias building from registry data and curated trade names"
```

---

### Task 10: The match ladder

**Files:**
- Create: `app/companies/matching/matcher.py`
- Test: `tests/test_matching_matcher.py`

**Interfaces:**
- Consumes: `normalize.normalize_name`, `normalize.tokens`, models `Company`, `CompanyAlias`.
- Produces: `MatchResult` (dataclass: `company_id: int`, `method: str`, `score: float`), `resolve(session, ticker: str | None, name: str | None, isin: str | None = None) -> MatchResult | None`, `FUZZY_MIN_SCORE`, `FUZZY_MIN_MARGIN`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_matching_matcher.py`:

```python
import pytest

from app.companies.matching import aliases, matcher
from app.models import Company


@pytest.fixture()
def universe(db_session):
    rows = [
        ("RELIANCE.NS", "Reliance Industries Limited", "oil_gas", "INE002A01018", "NORMAL"),
        ("APOLLOTYRE.NS", "Apollo Tyres Limited", "auto", "INE438A01022", "NORMAL"),
        ("APOLLOHOSP.NS", "Apollo Hospitals Enterprise Limited", "pharma", "INE437A01024", "NORMAL"),
        ("BHARATGEAR.NS", "Bharat Gears Limited", "auto", "INE561A01011", "NORMAL"),
        ("BHARATSEAT.NS", "Bharat Seats Limited", "auto", "INE785A01026", "NORMAL"),
        ("SBIN.NS", "State Bank of India", "banking", "INE062A01020", "NORMAL"),
        ("SBICARD.NS", "SBI Cards and Payment Services Limited", "banking", "INE018E01016", "NORMAL"),
        ("SHELL.BO", "Reliance Industries Limited", "other", "INE999Z01099", "SUSPENDED"),
    ]
    for ticker, name, sector, isin, tradeability in rows:
        db_session.add(Company(
            ticker=ticker, name=name, sector=sector, index_tier="OTHER",
            isin=isin, tradeability=tradeability,
        ))
    db_session.commit()
    aliases.rebuild_aliases(db_session)
    return db_session


def _company_id(session, ticker):
    return session.query(Company).filter_by(ticker=ticker).one().id


def test_exact_ticker_wins(universe):
    result = matcher.resolve(universe, ticker="APOLLOTYRE.NS", name=None)
    assert result.company_id == _company_id(universe, "APOLLOTYRE.NS")
    assert result.method == "ticker"


def test_isin_match(universe):
    result = matcher.resolve(universe, ticker=None, name=None, isin="INE437A01024")
    assert result.company_id == _company_id(universe, "APOLLOHOSP.NS")
    assert result.method == "isin"


def test_alias_exact_match(universe):
    result = matcher.resolve(universe, ticker=None, name="Apollo Tyres Ltd")
    assert result.company_id == _company_id(universe, "APOLLOTYRE.NS")
    assert result.method == "alias"


def test_token_set_match_ignores_word_order(universe):
    result = matcher.resolve(universe, ticker=None, name="Tyres Apollo Limited")
    assert result.company_id == _company_id(universe, "APOLLOTYRE.NS")
    assert result.method == "token_set"


def test_apollo_alone_is_ambiguous_and_returns_none(universe):
    assert matcher.resolve(universe, ticker=None, name="Apollo") is None


def test_bharat_collision_does_not_mismatch(universe):
    result = matcher.resolve(universe, ticker=None, name="Bharat Gears")
    assert result.company_id == _company_id(universe, "BHARATGEAR.NS")


def test_bare_bharat_returns_none(universe):
    assert matcher.resolve(universe, ticker=None, name="Bharat") is None


def test_sbi_does_not_match_sbi_cards(universe):
    result = matcher.resolve(universe, ticker=None, name="SBI Cards")
    assert result.company_id == _company_id(universe, "SBICARD.NS")


def test_unknown_name_returns_none(universe):
    assert matcher.resolve(universe, ticker=None, name="Totally Fictional Corp") is None


def test_unknown_ticker_falls_through_to_name(universe):
    result = matcher.resolve(universe, ticker="WRONG.NS", name="Apollo Tyres Limited")
    assert result.company_id == _company_id(universe, "APOLLOTYRE.NS")


def test_normal_company_beats_suspended_shell_on_identical_name(universe):
    result = matcher.resolve(universe, ticker=None, name="Reliance Industries Limited")
    assert result.company_id == _company_id(universe, "RELIANCE.NS")
    assert result.method.endswith("tradeability_tiebreak")


def test_empty_input_returns_none(universe):
    assert matcher.resolve(universe, ticker=None, name=None) is None
    assert matcher.resolve(universe, ticker="", name="  ") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_matching_matcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.matching.matcher'`

- [ ] **Step 3: Implement**

Create `app/companies/matching/matcher.py`:

```python
"""The match ladder (spec §8.3). Replaces
app.companies.resolution._find_direct_company.

Every rung is an EXACT comparison on a normalized form and every rung
resolves ambiguity to None -- preserving the resolver's "omit rather than
mismatch" contract while removing the substring matching that silently
mismatched companies. The one tiebreak allowed: when exactly one candidate
is normally tradeable and the rest are SME or suspended shells, the
tradeable one wins.

Lookups are indexed queries against company_aliases, not the old full-table
scan into Python, so growing the universe from 509 to ~4,967 does not slow
resolution proportionally.
"""
from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.companies.matching.normalize import normalize_name, tokens
from app.models import Company, CompanyAlias

FUZZY_MIN_SCORE = 0.90
FUZZY_MIN_MARGIN = 0.05


@dataclass(frozen=True)
class MatchResult:
    company_id: int
    method: str
    score: float = 1.0


def _disambiguate(session: Session, company_ids: list[int], method: str) -> MatchResult | None:
    """One candidate wins outright. Several candidates resolve to None,
    unless exactly one of them is normally tradeable -- the realistic
    collision once dormant shells enter the table."""
    unique = list(dict.fromkeys(company_ids))
    if not unique:
        return None
    if len(unique) == 1:
        return MatchResult(unique[0], method)

    tradeable = [
        company_id for company_id, in session.query(Company.id)
        .filter(Company.id.in_(unique), Company.tradeability == "NORMAL").all()
    ]
    if len(tradeable) == 1:
        return MatchResult(tradeable[0], f"{method}+tradeability_tiebreak")
    return None


def resolve(
    session: Session, ticker: str | None, name: str | None, isin: str | None = None,
) -> MatchResult | None:
    if ticker:
        company = session.query(Company).filter_by(ticker=ticker.strip()).one_or_none()
        if company is not None:
            return MatchResult(company.id, "ticker")

    if isin:
        company = session.query(Company).filter_by(isin=isin.strip().upper()).one_or_none()
        if company is not None:
            return MatchResult(company.id, "isin")

    normalized = normalize_name(name)
    if not normalized:
        return None

    exact = [
        company_id for company_id, in
        session.query(CompanyAlias.company_id).filter_by(normalized=normalized).all()
    ]
    if exact:
        return _disambiguate(session, exact, "alias")

    mention_tokens = tokens(name)
    if not mention_tokens:
        return None

    candidates = (
        session.query(CompanyAlias.company_id, CompanyAlias.normalized).all()
    )

    token_hits = [
        company_id for company_id, alias_normalized in candidates
        if frozenset(alias_normalized.split(" ")) == mention_tokens
    ]
    if token_hits:
        return _disambiguate(session, token_hits, "token_set")

    scored: list[tuple[float, int]] = []
    for company_id, alias_normalized in candidates:
        # Only score aliases that share at least one token -- without this
        # gate every unrelated name gets a similarity score and the margin
        # test becomes meaningless.
        if not (frozenset(alias_normalized.split(" ")) & mention_tokens):
            continue
        score = SequenceMatcher(None, normalized, alias_normalized).ratio()
        if score >= FUZZY_MIN_SCORE:
            scored.append((score, company_id))

    if not scored:
        return None
    scored.sort(reverse=True)
    best_score, best_id = scored[0]
    runners = [s for s, cid in scored if cid != best_id]
    if runners and best_score - max(runners) < FUZZY_MIN_MARGIN:
        return None
    return MatchResult(best_id, "fuzzy", best_score)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_matching_matcher.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add app/companies/matching/matcher.py tests/test_matching_matcher.py
git commit -m "feat: exact-first match ladder with ambiguity-to-none semantics"
```

---

### Task 11: Adversarial and regression gate

**Files:**
- Create: `tests/test_matching_gate.py`
- Create: `export_match_corpus.py`
- Test: `tests/test_matching_gate.py`

**Interfaces:**
- Consumes: `matcher.resolve`, `aliases.rebuild_aliases`.
- Produces: `tests/fixtures/matching/adversarial.json`; script `export_match_corpus.py` writing `tests/fixtures/matching/regression_corpus.json`.

The adversarial set is the gate: misses are acceptable, mismatches are not.

- [ ] **Step 1: Create the adversarial fixture**

Create `tests/fixtures/matching/adversarial.json`:

```json
{
  "companies": [
    {"ticker": "APOLLOTYRE.NS", "name": "Apollo Tyres Limited", "sector": "auto"},
    {"ticker": "APOLLOHOSP.NS", "name": "Apollo Hospitals Enterprise Limited", "sector": "pharma"},
    {"ticker": "BHARATGEAR.NS", "name": "Bharat Gears Limited", "sector": "auto"},
    {"ticker": "BHARATSEAT.NS", "name": "Bharat Seats Limited", "sector": "auto"},
    {"ticker": "BBL.NS", "name": "Bharat Bijlee Limited", "sector": "infra"},
    {"ticker": "SBIN.NS", "name": "State Bank of India", "sector": "banking"},
    {"ticker": "SBICARD.NS", "name": "SBI Cards and Payment Services Limited", "sector": "banking"},
    {"ticker": "SBILIFE.NS", "name": "SBI Life Insurance Company Limited", "sector": "banking"},
    {"ticker": "HDFCBANK.NS", "name": "HDFC Bank Limited", "sector": "banking"},
    {"ticker": "HDFCAMC.NS", "name": "HDFC Asset Management Company Limited", "sector": "banking"},
    {"ticker": "COALINDIA.NS", "name": "Coal India Limited", "sector": "metals"},
    {"ticker": "OIL.NS", "name": "Oil India Limited", "sector": "oil_gas"}
  ],
  "cases": [
    {"mention": "Apollo Tyres", "expect": "APOLLOTYRE.NS"},
    {"mention": "Apollo Hospitals", "expect": "APOLLOHOSP.NS"},
    {"mention": "Apollo", "expect": null},
    {"mention": "Bharat Gears Ltd", "expect": "BHARATGEAR.NS"},
    {"mention": "Bharat Seats", "expect": "BHARATSEAT.NS"},
    {"mention": "Bharat Bijlee", "expect": "BBL.NS"},
    {"mention": "Bharat", "expect": null},
    {"mention": "SBI Cards", "expect": "SBICARD.NS"},
    {"mention": "SBI Life", "expect": "SBILIFE.NS"},
    {"mention": "State Bank of India", "expect": "SBIN.NS"},
    {"mention": "HDFC Bank", "expect": "HDFCBANK.NS"},
    {"mention": "HDFC Asset Management", "expect": "HDFCAMC.NS"},
    {"mention": "Coal India", "expect": "COALINDIA.NS"},
    {"mention": "Oil India", "expect": "OIL.NS"},
    {"mention": "India", "expect": null},
    {"mention": "Some Company That Does Not Exist", "expect": null}
  ]
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_matching_gate.py`:

```python
import json
from pathlib import Path

import pytest

from app.companies.matching import aliases, matcher
from app.models import Company

ADVERSARIAL = Path(__file__).parent / "fixtures" / "matching" / "adversarial.json"
REGRESSION = Path(__file__).parent / "fixtures" / "matching" / "regression_corpus.json"


def _seed(session, companies):
    for entry in companies:
        session.add(Company(
            ticker=entry["ticker"], name=entry["name"], sector=entry["sector"],
            index_tier="OTHER", tradeability="NORMAL",
        ))
    session.commit()
    aliases.rebuild_aliases(session)


def test_adversarial_set_has_zero_mismatches(db_session):
    payload = json.loads(ADVERSARIAL.read_text(encoding="utf-8"))
    _seed(db_session, payload["companies"])

    mismatches = []
    for case in payload["cases"]:
        result = matcher.resolve(db_session, ticker=None, name=case["mention"])
        actual = (
            db_session.get(Company, result.company_id).ticker if result else None
        )
        # A miss (None where a ticker was expected) is tolerated. Returning
        # the WRONG company is the failure this gate exists to prevent.
        if actual is not None and actual != case["expect"]:
            mismatches.append((case["mention"], case["expect"], actual))

    assert mismatches == [], f"matcher returned wrong companies: {mismatches}"


def test_adversarial_set_hit_rate_is_acceptable(db_session):
    payload = json.loads(ADVERSARIAL.read_text(encoding="utf-8"))
    _seed(db_session, payload["companies"])

    expected = [c for c in payload["cases"] if c["expect"] is not None]
    hits = 0
    for case in expected:
        result = matcher.resolve(db_session, ticker=None, name=case["mention"])
        if result and db_session.get(Company, result.company_id).ticker == case["expect"]:
            hits += 1
    assert hits >= len(expected) - 1, f"only {hits}/{len(expected)} resolved"


@pytest.mark.skipif(not REGRESSION.exists(), reason="run export_match_corpus.py first")
def test_regression_corpus_has_zero_mismatches(db_session):
    payload = json.loads(REGRESSION.read_text(encoding="utf-8"))
    _seed(db_session, payload["companies"])

    mismatches = []
    for case in payload["cases"]:
        result = matcher.resolve(db_session, ticker=None, name=case["mention"])
        actual = (
            db_session.get(Company, result.company_id).ticker if result else None
        )
        if actual is not None and actual != case["expect"]:
            mismatches.append((case["mention"], case["expect"], actual))
    assert mismatches == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_matching_gate.py -v`
Expected: FAIL — `FileNotFoundError` for `adversarial.json` if step 1 was skipped, otherwise assertion failures naming the mismatches.

- [ ] **Step 4: Write the corpus exporter**

Create `backend/export_match_corpus.py`:

```python
"""Export the real article->company links already in the DB as a matcher
regression corpus.

The 881 alert_companies rows are genuine production resolutions. Replaying
company NAMES through the new matcher and asserting it never returns a
DIFFERENT company is a far stronger check than any synthetic fixture.

Run:  python export_match_corpus.py
Writes tests/fixtures/matching/regression_corpus.json
"""
import json
from pathlib import Path

from app.db import SessionLocal
from app.models import AlertCompany, Company

OUTPUT = Path("tests/fixtures/matching/regression_corpus.json")


def main() -> None:
    session = SessionLocal()
    try:
        linked_ids = {
            company_id for company_id, in
            session.query(AlertCompany.company_id).distinct().all()
        }
        companies = (
            session.query(Company).filter(Company.id.in_(linked_ids)).all()
            if linked_ids else []
        )
        payload = {
            "companies": [
                {"ticker": c.ticker, "name": c.name, "sector": c.sector}
                for c in companies
            ],
            "cases": [
                {"mention": c.name, "expect": c.ticker} for c in companies
            ],
        }
    finally:
        session.close()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {len(payload['cases'])} cases to {OUTPUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Generate the corpus and run the gate**

Run: `python export_match_corpus.py`
Expected: `wrote N cases to tests/fixtures/matching/regression_corpus.json` where N > 0.

Run: `python -m pytest tests/test_matching_gate.py -v`
Expected: 3 passed. If mismatches appear, fix `matcher.py` or add the offending name to `curated.py` — do NOT loosen the gate.

- [ ] **Step 6: Commit**

```bash
git add tests/test_matching_gate.py tests/fixtures/matching export_match_corpus.py
git commit -m "test: adversarial and production-derived regression gate for the matcher"
```

---

### Task 12: Swap resolution to the matcher

**Files:**
- Modify: `app/companies/resolution.py` — `_find_direct_company` (~line 64), fan-out query (~lines 175-187)
- Modify: `app/config.py`
- Test: `tests/test_resolution.py`

**AMENDED 2026-08-03 — concurrent work already changed this file.** Commit
`f39fd55` ("constrain sector fan-out to broad events, primary level, anchored
sub-sectors") landed on this branch from parallel work and rewrote the fan-out.
**Preserve all of it.** Specifically: `TOP_N_SECTOR_COMPANIES = 3` (do NOT restore
5), the `anchor_sub_sectors` parameter on `resolve_companies`, the
`Company.sub_sector.in_(anchors)` filter, and the `DEMO_TICKERS` filter. `_TIER_RANK`
is **kept**, demoted to a tiebreak behind market cap — the spec (§8.4) says "with
`index_tier` as tiebreak", so keeping it is correct. This task adds exactly two
filters and one ordering key. Nothing else in the fan-out changes.

**Interfaces:**
- Consumes: `matcher.resolve`.
- Produces: unchanged public surface — `resolve_companies(session, mentions) -> list[dict]`.

`settings.use_alias_matcher` gates the swap so the previous behaviour is restorable by env var without a deploy.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_resolution.py`:

```python
Reuse the file's existing `_make_company` helper and construct `CompanyMention`
the way the existing tests in this file already do — do NOT add a duplicate
mention factory. `resolve_companies`' second parameter (`anchor_sub_sectors`)
has a default, so two-argument calls remain valid.

```python
from app.companies.matching import aliases


def _sector_mention(sector):
    return CompanyMention(
        name=None, ticker=None, is_direct=False, sector=sector,
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0,
        rationale="r", key_points=[], confidence_score=50, time_horizon="Short-Term",
    )


def _name_mention(name):
    return CompanyMention(
        name=name, ticker=None, is_direct=True, sector=None,
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0,
        rationale="r", key_points=[], confidence_score=50, time_horizon="Short-Term",
    )


def test_matcher_resolves_a_name_without_a_ticker(db_session):
    _make_company(db_session, "APOLLOTYRE.NS", "Apollo Tyres Limited", "auto", None)
    aliases.rebuild_aliases(db_session)

    resolved = resolve_companies(db_session, [_name_mention("Apollo Tyres Ltd")])
    assert len(resolved) == 1


def test_ambiguous_name_resolves_to_nothing(db_session):
    _make_company(db_session, "APOLLOTYRE.NS", "Apollo Tyres Limited", "auto", None)
    _make_company(db_session, "APOLLOHOSP.NS", "Apollo Hospitals Enterprise Limited", "pharma", None)
    aliases.rebuild_aliases(db_session)

    assert resolve_companies(db_session, [_name_mention("Apollo")]) == []


def test_sector_fanout_ranks_by_market_cap(db_session):
    # BIG is in the lowest index tier but is far larger. Under the old
    # _TIER_RANK-first ordering SMALL won; market cap now leads.
    _make_company(db_session, "BIG.NS", "Big Oil Limited", "oil_gas", 900000.0, index_tier="OTHER")
    _make_company(db_session, "SMALL.NS", "Small Oil Limited", "oil_gas", 100.0, index_tier="NIFTY50")

    resolved = resolve_companies(db_session, [_sector_mention("oil_gas")])
    assert db_session.get(Company, resolved[0]["company_id"]).ticker == "BIG.NS"


def test_sector_fanout_still_falls_back_to_index_tier_without_caps(db_session):
    # Guards the concurrent work in f39fd55: when no company has a market
    # cap, nullslast() leaves every row tied and _TIER_RANK must still
    # decide the order.
    _make_company(db_session, "LOW.NS", "Low Tier Oil Limited", "oil_gas", None, index_tier="OTHER")
    _make_company(db_session, "HIGH.NS", "High Tier Oil Limited", "oil_gas", None, index_tier="NIFTY50")

    resolved = resolve_companies(db_session, [_sector_mention("oil_gas")])
    assert db_session.get(Company, resolved[0]["company_id"]).ticker == "HIGH.NS"


def test_sector_fanout_excludes_non_tradeable_companies(db_session):
    shell = _make_company(db_session, "SHELL.BO", "Dormant Shell Limited", "oil_gas", 5000000.0, index_tier="OTHER")
    shell.tradeability = "SUSPENDED"
    db_session.commit()
    _make_company(db_session, "REAL.NS", "Real Oil Limited", "oil_gas", 100.0, index_tier="OTHER")

    resolved = resolve_companies(db_session, [_sector_mention("oil_gas")])
    tickers = {db_session.get(Company, r["company_id"]).ticker for r in resolved}
    assert tickers == {"REAL.NS"}


def test_sector_fanout_excludes_global_companies(db_session):
    xom = _make_company(db_session, "XOM", "Exxon Mobil", "oil_gas", 9000000.0, index_tier="GLOBAL_LARGE_CAP")
    xom.market = "GLOBAL"
    db_session.commit()
    _make_company(db_session, "REAL.NS", "Real Oil Limited", "oil_gas", 100.0, index_tier="OTHER")

    resolved = resolve_companies(db_session, [_sector_mention("oil_gas")])
    tickers = {db_session.get(Company, r["company_id"]).ticker for r in resolved}
    assert tickers == {"REAL.NS"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_resolution.py -k "matcher or fanout or ambiguous" -v`
Expected: FAIL — `test_sector_fanout_ranks_by_market_cap` returns `SMALL.NS` first (index-tier ordering still wins), and the global/non-tradeable tests fail because no filter excludes those rows yet.

- [ ] **Step 3: Add the config flag**

In `app/config.py`, inside `class Settings`, after `zerodha_hub_url`:

```python
    # Gates app.companies.matching.matcher (spec §8). Set to "false" to
    # restore the pre-rebuild substring resolver without a deploy.
    use_alias_matcher: bool = os.environ.get("USE_ALIAS_MATCHER", "true").lower() == "true"
```

- [ ] **Step 4: Rewrite the direct-mention resolver**

In `app/companies/resolution.py`, replace the body of `_find_direct_company` (lines 64-93) with:

```python
def _find_direct_company(session: Session, mention: CompanyMention) -> Company | None:
    """Resolve a direct mention via the alias match ladder
    (app.companies.matching.matcher).

    The previous implementation loaded every company into Python and
    substring-matched both directions. At 509 companies that was merely
    slow; at ~4,967 it silently mismatches (many companies share leading
    tokens) so it was replaced. Ambiguity still resolves to None -- the
    "omit rather than mismatch" contract is unchanged.
    """
    if not settings.use_alias_matcher:
        return _find_direct_company_legacy(session, mention)

    result = matcher.resolve(session, ticker=mention.ticker, name=mention.name)
    if result is None:
        return None
    company = session.get(Company, result.company_id)
    if company is None or is_demo_company(company.ticker):
        return None
    return company
```

Rename the original function to `_find_direct_company_legacy` and keep it directly below, unchanged, so the flag has something to fall back to. Add to the imports at the top of the file:

```python
from app.companies.matching import matcher
from app.config import settings
```

- [ ] **Step 5: Replace the fan-out ordering**

**Keep `_TIER_RANK`** — it becomes the tiebreak, per spec §8.4. Keep
`TOP_N_SECTOR_COMPANIES = 3`, the `anchor_sub_sectors` parameter, and the
`anchors` filter exactly as `f39fd55` left them.

In `app/companies/resolution.py`, make two changes inside the existing fan-out
block. Add the two filters to the base query:

```python
            query = (
                session.query(Company)
                .filter_by(sector=mention.sector)
                .filter(Company.ticker.notin_(DEMO_TICKERS))
                # Dormant shells and non-Indian rows must never surface as
                # affected companies once the universe grows from 509 to
                # ~4,967 (spec §8.4).
                .filter(Company.market == "INDIA")
                .filter(Company.tradeability == "NORMAL")
            )
```

and change only the `order_by` in the block below it:

```python
            companies = (
                # Rank by real size, not Nifty membership: after the full
                # universe ingest ~4,200 of ~4,967 companies sit in
                # index_tier='OTHER', which collapses the tier ranking into
                # alphabetical order. _TIER_RANK stays as the tiebreak, which
                # is also what keeps the pre-existing fan-out tests (whose
                # companies have no market cap) ordering as before.
                query.order_by(
                    Company.market_cap.desc().nullslast(),
                    _TIER_RANK.asc(),
                    Company.ticker.asc(),
                )
                .limit(TOP_N_SECTOR_COMPANIES)
                .all()
            )
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_resolution.py -v`
Expected: all pass, including the pre-existing tests in that file.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q`
Expected: no new failures against the 814-test baseline. `tests/test_cascade.py` and `tests/test_end_to_end.py` exercise fan-out. The pre-existing fan-out tests in `tests/test_resolution.py` pass `market_cap=None`, so `nullslast()` plus the retained `_TIER_RANK` tiebreak must leave their ordering unchanged — **if any of them break, the fix is in your change, not in their assertions.** Do not edit tests written by the concurrent `f39fd55` work to make your change pass; report it as a concern instead.

- [ ] **Step 8: Commit**

```bash
git add app/companies/resolution.py app/config.py tests/test_resolution.py
git commit -m "feat: resolve direct mentions via alias matcher, rank fan-out by market cap"
```

---

# Phase 6 — Cap Tiers

### Task 13: Rank-based MICRO and cap-tier resolution with provenance

**Files:**
- Modify: `app/config.py`
- Modify: `app/market/cap_tier.py`
- Test: `tests/test_cap_tier.py`

**Interfaces:**
- Consumes: `Company.market_cap`, `Company.market_cap_source`, `Company.market_cap_as_of`, `Company.amfi_tier`, `Company.amfi_as_of`.
- Produces: `CapTier` (dataclass: `tier: str`, `source: str`, `as_of: date | None`), `resolve_cap_tier(session, company, today: date | None = None) -> CapTier | None`. `compute_cap_tiers` keeps its `list[tuple[str, float]] -> dict[str, str]` signature.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cap_tier.py`:

```python
from datetime import date, timedelta

from app.market.cap_tier import resolve_cap_tier
from app.models import Company

TODAY = date(2026, 8, 3)


def test_rank_501_and_beyond_is_micro():
    companies = [(f"T{i}.NS", float(10000 - i)) for i in range(600)]
    tiers = cap_tier.compute_cap_tiers(companies)
    assert tiers["T499.NS"] == "SMALL"
    assert tiers["T500.NS"] == "MICRO"
    assert tiers["T599.NS"] == "MICRO"


def _seed(session, count=600, **kw):
    for i in range(count):
        session.add(Company(
            ticker=f"T{i}.NS", name=f"Company {i}", sector="other", index_tier="OTHER",
            market_cap=float(10000 - i), market_cap_source="BSE", market_cap_as_of=TODAY,
            **({} if i else kw),
        ))
    session.commit()


def test_derived_tier_reports_market_cap_provenance(db_session):
    _seed(db_session, count=5)
    company = db_session.query(Company).filter_by(ticker="T0.NS").one()
    resolved = resolve_cap_tier(db_session, company, today=TODAY)
    assert resolved.tier == "LARGE"
    assert resolved.source == "derived from BSE 2026-08-03"


def test_amfi_tier_takes_precedence(db_session):
    _seed(db_session, count=5, amfi_tier="MID", amfi_rank=120, amfi_as_of=TODAY)
    company = db_session.query(Company).filter_by(ticker="T0.NS").one()
    resolved = resolve_cap_tier(db_session, company, today=TODAY)
    assert resolved.tier == "MID"
    assert resolved.source == "AMFI 2026-08-03"


def test_amfi_small_with_derived_micro_rank_reports_micro(db_session):
    _seed(db_session, count=600, amfi_tier="SMALL", amfi_rank=900, amfi_as_of=TODAY)
    # T0 has the largest cap, so give the AMFI values to a rank-501+ company.
    company = db_session.query(Company).filter_by(ticker="T550.NS").one()
    company.amfi_tier = "SMALL"
    company.amfi_as_of = TODAY
    db_session.commit()
    resolved = resolve_cap_tier(db_session, company, today=TODAY)
    assert resolved.tier == "MICRO"
    assert "NSE index methodology" in resolved.source


def test_stale_market_cap_withholds_the_tier(db_session):
    _seed(db_session, count=5)
    company = db_session.query(Company).filter_by(ticker="T0.NS").one()
    company.market_cap_as_of = TODAY - timedelta(days=400)
    db_session.commit()
    assert resolve_cap_tier(db_session, company, today=TODAY) is None


def test_missing_market_cap_returns_none(db_session):
    company = Company(
        ticker="NOCAP.NS", name="No Cap Ltd", sector="other", index_tier="OTHER",
    )
    db_session.add(company)
    db_session.commit()
    assert resolve_cap_tier(db_session, company, today=TODAY) is None


def test_global_company_never_gets_a_tier(db_session):
    company = Company(
        ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP",
        market="GLOBAL", market_cap=3000000.0, market_cap_source="yfinance",
        market_cap_as_of=TODAY,
    )
    db_session.add(company)
    db_session.commit()
    assert resolve_cap_tier(db_session, company, today=TODAY) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cap_tier.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_cap_tier'`.

- [ ] **Step 3: Add the config constants**

In `app/config.py`, replace the `MICRO_CAP_FLOOR` block with:

```python
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
```

- [ ] **Step 4: Rewrite cap_tier.py**

Replace the body of `compute_cap_tiers` in `app/market/cap_tier.py` and append `resolve_cap_tier`:

```python
    ranked = sorted(companies, key=lambda tc: tc[1], reverse=True)
    tiers: dict[str, str] = {}
    for rank, (ticker, _cap) in enumerate(ranked, start=1):
        if rank <= config.AMFI_LARGE_CAP_RANK_CUTOFF:
            tiers[ticker] = "LARGE"
        elif rank <= config.AMFI_MID_CAP_RANK_CUTOFF:
            tiers[ticker] = "MID"
        elif rank <= config.MICRO_CAP_RANK_CUTOFF:
            tiers[ticker] = "SMALL"
        else:
            tiers[ticker] = "MICRO"
    return tiers
```

Then append to the same file:

```python
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class CapTier:
    tier: str
    source: str
    as_of: date | None


def _is_stale(as_of: date | None, max_age_days: int, today: date) -> bool:
    """A missing as_of is treated as stale: an undated value cannot be shown
    as current."""
    if as_of is None:
        return True
    return (today - as_of) > timedelta(days=max_age_days)


def resolve_cap_tier(session: Session, company: Company, today: date | None = None) -> CapTier | None:
    """The single entry point for a company's cap tier (spec §7).

    Precedence: AMFI's published tier where present and fresh, otherwise the
    tier derived from exchange-published caps. Returns None -- never a
    guess -- when the company is not Indian, has no market cap, or its cap
    is too stale to rank honestly.

    AMFI publishes only LARGE/MID/SMALL; MICRO is a subdivision of AMFI's
    open-ended SMALL band using NSE's index methodology, and the reported
    source says so rather than crediting AMFI with a label it never
    published.
    """
    today = today or date.today()
    if company.market != "INDIA":
        return None
    if company.market_cap is None:
        return None
    if _is_stale(company.market_cap_as_of, config.MARKET_CAP_MAX_AGE_DAYS, today):
        return None

    derived = compute_cap_tier_for_ticker(session, company.ticker)
    if derived is None:
        return None

    amfi_fresh = (
        company.amfi_tier
        and not _is_stale(company.amfi_as_of, config.AMFI_MAX_AGE_DAYS, today)
    )
    if not amfi_fresh:
        source = f"derived from {company.market_cap_source or 'unknown'} {company.market_cap_as_of.isoformat()}"
        return CapTier(derived, source, company.market_cap_as_of)

    amfi_stamp = f"AMFI {company.amfi_as_of.isoformat()}"
    if company.amfi_tier == "SMALL" and derived == "MICRO":
        return CapTier("MICRO", f"{amfi_stamp} + NSE index methodology", company.amfi_as_of)
    return CapTier(company.amfi_tier, amfi_stamp, company.amfi_as_of)
```

Add `from app.models import Company` if it is not already imported (it is, at line 11).

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_cap_tier.py -v`
Expected: all pass, including the four pre-existing tests.

- [ ] **Step 6: Find and fix any other MICRO_CAP_FLOOR reference**

Run: `grep -rn "MICRO_CAP_FLOOR" app tests`
Expected: no results. If any remain, update them to `MICRO_CAP_RANK_CUTOFF` semantics and rerun `python -m pytest -q`.

- [ ] **Step 7: Commit**

```bash
git add app/config.py app/market/cap_tier.py tests/test_cap_tier.py
git commit -m "feat: rank-based MICRO tier and cap-tier resolution with provenance"
```

---

# Phase 7 — Migration and Rollout

### Task 14: Backfill the existing 509 and fix broken tickers

**Files:**
- Create: `backend/backfill_universe.py`
- Test: `tests/test_backfill_universe.py`

**Interfaces:**
- Consumes: `normalize.build_records`, `loader.upsert_records`, `aliases.rebuild_aliases`.
- Produces: `TICKER_CORRECTIONS: dict[str, str]`, `apply_ticker_corrections(session) -> list[tuple[str, str]]`, `flag_missing_tickers(session, known_symbols: set[str]) -> list[str]`, `merge_duplicate_companies(session, pairs) -> list[dict]`.

Verified against the live NSE master on 2026-08-03: `HPCL` and `OILINDIA` are not NSE symbols; the real ones are `HINDPETRO` and `OIL`. `JBCHEPHARM` is absent from the master entirely.

**AMENDED 2026-08-03 — the real data is not the shape this task assumed.** Task 11's
regression corpus surfaced the actual rows. `HPCL.NS` and `OILINDIA.NS` are not
mis-typed tickers on the real companies; they are **spurious duplicate rows sitting
alongside the correct ones**:

| id | ticker | ISIN | alert_companies rows |
|---|---|---|---|
| 271 | `HINDPETRO.NS` | INE094A01015 | 5 |
| 1016 | `HPCL.NS` | *none* | 2 |
| 385 | `OIL.NS` | INE274J01014 | 2 |
| 1017 | `OILINDIA.NS` | *none* | 1 |
| 305 | `JBCHEPHARM.NS` | INE572A01036 | 0 |

Consequences for this task:

1. `apply_ticker_corrections` will correctly SKIP both renames (the target ticker
   already exists) — but that leaves **3 alert rows attached to phantom companies
   that have no ISIN and will never appear in the exchange masters**. Skipping is
   necessary but not sufficient, so this task now also implements
   `merge_duplicate_companies` (below).
2. The claim that `JBCHEPHARM.NS` must not be deleted because "it has alert history"
   is **factually wrong** — it has 0 alerts. It carries a valid ISIN and is a real
   company simply absent from the current NSE master (delisted or merged). Flagging
   it `SUSPENDED` remains correct, but for that reason, not the stated one. Fix the
   docstring accordingly.

- [ ] **Step 1: Write the failing test**

Create `tests/test_backfill_universe.py`:

```python
import backfill_universe
from app.companies.matching import aliases
from app.models import Alert, AlertCompany, Article, Company, CompanyAlias


def _alert(session):
    """Alert.article_id is nullable=False, so an Article must exist first."""
    article = Article(source="test", url="https://example.test/1", title="t", content="c")
    session.add(article)
    session.commit()
    alert = Alert(article_id=article.id, category="test")
    session.add(alert)
    session.commit()
    return alert


def test_broken_tickers_are_corrected_in_place(db_session):
    company = Company(
        ticker="HPCL.NS", name="Hindustan Petroleum Corporation Ltd.",
        sector="oil_gas", index_tier="NIFTY50",
    )
    db_session.add(company)
    db_session.commit()
    original_id = company.id

    changed = backfill_universe.apply_ticker_corrections(db_session)
    assert ("HPCL.NS", "HINDPETRO.NS") in changed
    refreshed = db_session.get(Company, original_id)
    assert refreshed.ticker == "HINDPETRO.NS"
    assert refreshed.id == original_id


def test_correction_preserves_alert_history(db_session):
    company = Company(
        ticker="OILINDIA.NS", name="Oil India Ltd.", sector="oil_gas", index_tier="NIFTY50",
    )
    db_session.add(company)
    db_session.commit()
    alert = _alert(db_session)
    db_session.add(AlertCompany(alert_id=alert.id, company_id=company.id, direction="POSITIVE"))
    db_session.commit()

    backfill_universe.apply_ticker_corrections(db_session)
    assert db_session.query(AlertCompany).one().company_id == company.id
    assert db_session.get(Company, company.id).ticker == "OIL.NS"


def test_correction_is_skipped_when_target_already_exists(db_session):
    db_session.add(Company(
        ticker="HINDPETRO.NS", name="Hindustan Petroleum", sector="oil_gas", index_tier="NIFTY50",
    ))
    db_session.add(Company(
        ticker="HPCL.NS", name="Hindustan Petroleum Corporation Ltd.",
        sector="oil_gas", index_tier="NIFTY50",
    ))
    db_session.commit()

    changed = backfill_universe.apply_ticker_corrections(db_session)
    assert ("HPCL.NS", "HINDPETRO.NS") not in changed
    assert db_session.query(Company).filter_by(ticker="HPCL.NS").count() == 1


def test_unknown_ticker_is_flagged_suspended_not_deleted(db_session):
    company = Company(
        ticker="JBCHEPHARM.NS", name="JB Chemicals", sector="pharma", index_tier="NIFTYMIDCAP150",
    )
    db_session.add(company)
    db_session.commit()

    flagged = backfill_universe.flag_missing_tickers(db_session, known_symbols={"RELIANCE"})
    assert flagged == ["JBCHEPHARM.NS"]
    refreshed = db_session.get(Company, company.id)
    assert refreshed is not None
    assert refreshed.tradeability == "SUSPENDED"


def test_merge_moves_alert_history_and_deletes_the_phantom(db_session):
    canonical = Company(
        ticker="HINDPETRO.NS", name="Hindustan Petroleum Corporation Ltd.",
        sector="oil_gas", index_tier="NIFTY50", isin="INE094A01015",
    )
    phantom = Company(
        ticker="HPCL.NS", name="Hindustan Petroleum", sector="oil_gas",
        index_tier="OTHER",
    )
    db_session.add_all([canonical, phantom])
    db_session.commit()
    canonical_id, phantom_id = canonical.id, phantom.id

    alert = _alert(db_session)
    db_session.add(AlertCompany(alert_id=alert.id, company_id=phantom_id, direction="POSITIVE"))
    db_session.commit()

    report = backfill_universe.merge_duplicate_companies(
        db_session, [("HPCL.NS", "HINDPETRO.NS")],
    )

    assert db_session.get(Company, phantom_id) is None
    assert db_session.get(Company, canonical_id) is not None
    assert db_session.query(AlertCompany).one().company_id == canonical_id
    assert report[0]["moved"]["alert_companies.company_id"] == 1


def test_merge_refuses_when_the_phantom_has_an_isin(db_session):
    # The safety rule: never delete a company that carries an ISIN.
    db_session.add(Company(
        ticker="HINDPETRO.NS", name="Hindustan Petroleum Corporation Ltd.",
        sector="oil_gas", index_tier="NIFTY50", isin="INE094A01015",
    ))
    db_session.add(Company(
        ticker="HPCL.NS", name="Hindustan Petroleum", sector="oil_gas",
        index_tier="OTHER", isin="INE999Z01099",
    ))
    db_session.commit()

    report = backfill_universe.merge_duplicate_companies(
        db_session, [("HPCL.NS", "HINDPETRO.NS")],
    )
    assert "skipped" in report[0]
    assert db_session.query(Company).filter_by(ticker="HPCL.NS").count() == 1


def test_merge_refuses_when_the_canonical_has_no_isin(db_session):
    db_session.add(Company(
        ticker="HINDPETRO.NS", name="Hindustan Petroleum Corporation Ltd.",
        sector="oil_gas", index_tier="NIFTY50",
    ))
    db_session.add(Company(
        ticker="HPCL.NS", name="Hindustan Petroleum", sector="oil_gas", index_tier="OTHER",
    ))
    db_session.commit()

    report = backfill_universe.merge_duplicate_companies(
        db_session, [("HPCL.NS", "HINDPETRO.NS")],
    )
    assert "skipped" in report[0]
    assert db_session.query(Company).count() == 2


def test_merge_deletes_derivable_rows_rather_than_reassigning_them(db_session):
    canonical = Company(
        ticker="OIL.NS", name="Oil India Ltd.", sector="oil_gas",
        index_tier="NIFTY50", isin="INE274J01014",
    )
    phantom = Company(
        ticker="OILINDIA.NS", name="Oil India", sector="oil_gas", index_tier="OTHER",
    )
    db_session.add_all([canonical, phantom])
    db_session.commit()
    # Both companies normalize to aliases that would collide on reassignment.
    aliases.rebuild_aliases(db_session)
    assert db_session.query(CompanyAlias).filter_by(company_id=phantom.id).count() > 0

    backfill_universe.merge_duplicate_companies(db_session, [("OILINDIA.NS", "OIL.NS")])

    assert db_session.query(CompanyAlias).filter_by(company_id=phantom.id).count() == 0
    assert db_session.query(CompanyAlias).filter_by(company_id=canonical.id).count() > 0


def test_global_companies_are_never_flagged(db_session):
    db_session.add(Company(
        ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market="GLOBAL",
    ))
    db_session.commit()
    assert backfill_universe.flag_missing_tickers(db_session, known_symbols=set()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backfill_universe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backfill_universe'`

- [ ] **Step 3: Implement**

Create `backend/backfill_universe.py`:

```python
"""One-shot backfill for the 509 companies that predate the universe
ingest: adopt them into the ISIN-keyed model, correct broken tickers, and
flag any that no longer exist on an exchange.

Run AFTER a snapshot exists:
    python -c "from datetime import date; from app.companies.universe import fetchers; \\
        fetchers.fetch_nse_equity_list('data/universe', date.today()); \\
        fetchers.fetch_bse_scrip_list('data/universe', date.today())"
    python backfill_universe.py

Verified against the live NSE master on 2026-08-03: HPCL and OILINDIA are
not NSE symbols (the real ones are HINDPETRO and OIL) and JBCHEPHARM is
absent from the master entirely.
"""
import json
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.companies.matching import aliases
from app.companies.universe import fetchers, loader, normalize, snapshot
from app.db import SessionLocal
from app.models import Company

TICKER_CORRECTIONS = {
    "HPCL.NS": "HINDPETRO.NS",
    "OILINDIA.NS": "OIL.NS",
}


def apply_ticker_corrections(session: Session) -> list[tuple[str, str]]:
    """Rewrite known-wrong tickers in place. companies.id is untouched, so
    every alert_companies row and the whole price/outcome history survives.

    A correction whose target ticker already exists is SKIPPED rather than
    merged -- merging two companies means reassigning FK rows, which is a
    separate, deliberate operation. In this database BOTH corrections hit
    that path (see merge_duplicate_companies, which handles them).
    """
    changed = []
    for wrong, right in TICKER_CORRECTIONS.items():
        company = session.query(Company).filter_by(ticker=wrong).one_or_none()
        if company is None:
            continue
        if session.query(Company).filter_by(ticker=right).count():
            print(f"SKIP {wrong} -> {right}: target already exists, needs a manual merge")
            continue
        company.ticker = right
        changed.append((wrong, right))
    session.commit()
    return changed


def flag_missing_tickers(session: Session, known_symbols: set[str]) -> list[str]:
    """Mark Indian companies whose symbol is absent from the exchange master
    as SUSPENDED. Never deletes: a company that has left the exchange is
    still a real company with a real ISIN (JBCHEPHARM.NS, INE572A01036, is
    the live example), and a delisting is a fact to record, not a reason to
    erase the past. Deleting is reserved for the phantom no-ISIN duplicates
    that merge_duplicate_companies handles."""
    flagged = []
    for company in session.query(Company).filter(Company.market == "INDIA").all():
        symbol = company.ticker.rsplit(".", 1)[0]
        if symbol in known_symbols:
            continue
        company.tradeability = "SUSPENDED"
        flagged.append(company.ticker)
    session.commit()
    return flagged


DUPLICATE_MERGES = [
    # (phantom ticker, canonical ticker). Both phantoms were created without
    # an ISIN and duplicate a real company that has one.
    ("HPCL.NS", "HINDPETRO.NS"),
    ("OILINDIA.NS", "OIL.NS"),
]

# Derivable rows: regenerated by rebuild_aliases / the ingest, so the
# phantom's copies are deleted rather than reassigned (reassigning would
# collide with the canonical company's own rows on their unique keys).
_DERIVABLE_TABLES = ("company_aliases", "listings", "company_index_memberships")

# History rows: irreplaceable, so these are REASSIGNED to the canonical id.
# (table, column) for every remaining FK onto companies.id.
_HISTORY_FKS = (
    ("alert_companies", "company_id"),
    ("alert_companies", "parent_company_id"),
    ("impact_edges", "from_company_id"),
    ("impact_edges", "to_company_id"),
    ("calibration_samples", "company_id"),
    ("car_outcomes", "company_id"),
    ("market_moves", "company_id"),
    ("holdings", "company_id"),
    ("user_watchlist_companies", "company_id"),
)


def merge_duplicate_companies(session: Session, pairs=DUPLICATE_MERGES) -> list[dict]:
    """Fold a phantom duplicate company into the real one and delete it.

    Task 11's regression corpus proved these exist: HPCL.NS (no ISIN, 2
    alerts) shadowing HINDPETRO.NS (INE094A01015, 5 alerts), and
    OILINDIA.NS (no ISIN, 1 alert) shadowing OIL.NS (INE274J01014). The
    phantoms will never appear in an exchange master, so without a merge
    their alert history is stranded on rows that can never be enriched,
    ranked, or priced.

    SAFETY RULE, enforced not assumed: a merge only proceeds when the
    phantom has NO ISIN and the canonical HAS one. Anything else is
    reported and skipped -- this function must never be able to delete a
    real company.

    Derivable rows (aliases, listings, index memberships) are deleted
    because the canonical company already has its own and they regenerate.
    History rows are reassigned. A history row that would violate a unique
    constraint after reassignment is deleted instead, and counted, so the
    merge cannot fail partway and strand the rest.
    """
    report = []
    for phantom_ticker, canonical_ticker in pairs:
        phantom = session.query(Company).filter_by(ticker=phantom_ticker).one_or_none()
        canonical = session.query(Company).filter_by(ticker=canonical_ticker).one_or_none()
        if phantom is None or canonical is None:
            report.append({"phantom": phantom_ticker, "skipped": "not found"})
            continue
        if phantom.isin:
            report.append({"phantom": phantom_ticker, "skipped": "phantom has an ISIN -- not a phantom"})
            continue
        if not canonical.isin:
            report.append({"phantom": phantom_ticker, "skipped": "canonical has no ISIN -- cannot confirm identity"})
            continue

        moved: dict[str, int] = {}
        for table in _DERIVABLE_TABLES:
            result = session.execute(
                text(f"DELETE FROM {table} WHERE company_id = :pid"), {"pid": phantom.id},
            )
            if result.rowcount:
                moved[f"{table} (deleted)"] = result.rowcount

        for table, column in _HISTORY_FKS:
            result = session.execute(
                text(f"UPDATE {table} SET {column} = :cid WHERE {column} = :pid"),
                {"cid": canonical.id, "pid": phantom.id},
            )
            if result.rowcount:
                moved[f"{table}.{column}"] = result.rowcount

        session.delete(phantom)
        session.commit()
        report.append({
            "phantom": phantom_ticker, "canonical": canonical_ticker,
            "phantom_id": phantom.id, "canonical_id": canonical.id, "moved": moved,
        })
    return report


def main() -> None:
    root = snapshot.DEFAULT_ROOT
    day = snapshot.latest_snapshot_day(root)
    if day is None:
        raise SystemExit(f"no snapshot found under {root}; fetch the masters first")

    nse_rows = normalize.parse_nse_rows(
        snapshot.master_path(root, day, "nse_equity_l.csv").read_text(encoding="utf-8")
    )
    bse_rows = normalize.parse_bse_rows(
        snapshot.master_path(root, day, "bse_scrips.json").read_text(encoding="utf-8")
    )
    details = {
        p.stem: normalize.parse_bse_detail(p.read_text(encoding="utf-8"))
        for p in (snapshot.snapshot_dir(root, day) / snapshot.DETAIL_DIRNAME).glob("*.json")
    }

    session = SessionLocal()
    try:
        print("corrections:", apply_ticker_corrections(session))
        # Runs AFTER corrections (which will skip both, since the canonical
        # tickers already exist) and BEFORE the upsert, so the phantom rows
        # are gone before aliases are rebuilt for them.
        for entry in merge_duplicate_companies(session):
            print("merge:", entry)

        records = normalize.build_records(nse_rows, bse_rows, details, day)
        existing_tickers = {
            ticker for ticker, in
            session.query(Company.ticker).filter(Company.market == "INDIA").all()
        }
        # Backfill ONLY the companies already present. The full ingest is a
        # separate, later step (ingest_universe.py) so this run can never
        # grow the universe by accident.
        scoped = [r for r in records if r["ticker"] in existing_tickers]
        print("upsert:", loader.upsert_records(session, scoped))

        known = {r["SYMBOL"] for r in nse_rows} | {
            (r.get("scrip_id") or "").strip() for r in bse_rows
        }
        print("flagged missing:", flag_missing_tickers(session, known))
        print("aliases:", aliases.rebuild_aliases(session))
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backfill_universe.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backfill_universe.py tests/test_backfill_universe.py
git commit -m "feat: backfill existing companies into the ISIN model, fix broken tickers"
```

---

### Task 15: Mark globals and enforce the ISIN invariant

**Files:**
- Modify: `backend/backfill_universe.py`
- Test: `tests/test_backfill_universe.py`

**Interfaces:**
- Consumes: `global_seed.GLOBAL_COMPANIES`.
- Produces: `mark_global_companies(session) -> int`, `validate_isin_invariant(session) -> list[str]`.

Spec §5.1 specified a `CHECK` constraint. SQLite cannot add one via `ALTER TABLE`, so the invariant is enforced here and asserted by a test.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backfill_universe.py`:

```python
def test_curated_global_companies_are_marked(db_session):
    db_session.add(Company(
        ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP",
    ))
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries Limited", sector="oil_gas",
        index_tier="NIFTY50", isin="INE002A01018",
    ))
    db_session.commit()

    marked = backfill_universe.mark_global_companies(db_session)
    assert marked == 1
    assert db_session.query(Company).filter_by(ticker="AAPL").one().market == "GLOBAL"
    assert db_session.query(Company).filter_by(ticker="RELIANCE.NS").one().market == "INDIA"


def test_isin_invariant_reports_indian_companies_without_isin(db_session):
    db_session.add(Company(
        ticker="NOISIN.NS", name="No Isin Ltd", sector="other", index_tier="OTHER",
    ))
    db_session.add(Company(
        ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market="GLOBAL",
    ))
    db_session.commit()

    assert backfill_universe.validate_isin_invariant(db_session) == ["NOISIN.NS"]


def test_isin_invariant_passes_on_a_clean_universe(db_session):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries Limited", sector="oil_gas",
        index_tier="NIFTY50", isin="INE002A01018",
    ))
    db_session.commit()
    assert backfill_universe.validate_isin_invariant(db_session) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backfill_universe.py -k "global or invariant" -v`
Expected: FAIL with `AttributeError: module 'backfill_universe' has no attribute 'mark_global_companies'`

- [ ] **Step 3: Implement**

Append to `backend/backfill_universe.py`, above `main()`:

```python
from app.companies.global_seed import GLOBAL_COMPANIES


def mark_global_companies(session: Session) -> int:
    """Set market='GLOBAL' on the curated non-Indian list. These rows have
    no ISIN, no listings, and never receive a cap tier -- AMFI ranking is
    India-only and inventing a global scale would be exactly the kind of
    unsourced number this design rejects."""
    global_tickers = {entry["ticker"] for entry in GLOBAL_COMPANIES}
    marked = 0
    for company in session.query(Company).filter(Company.ticker.in_(global_tickers)).all():
        if company.market != "GLOBAL":
            company.market = "GLOBAL"
            marked += 1
    session.commit()
    return marked


def validate_isin_invariant(session: Session) -> list[str]:
    """Every market='INDIA' company must carry an ISIN.

    Spec §5.1 called for a CHECK constraint. SQLite cannot add one via
    ALTER TABLE (there is no Alembic in this project -- see app/db.py), so
    the invariant is enforced here and asserted in the test suite instead.
    Returns the offending tickers; an empty list means the universe is
    clean.
    """
    return [
        ticker for ticker, in session.query(Company.ticker)
        .filter(Company.market == "INDIA")
        .filter((Company.isin.is_(None)) | (Company.isin == ""))
        .all()
    ]
```

Then, in `main()`, insert immediately after the `print("corrections:", ...)` line:

```python
        print("globals marked:", mark_global_companies(session))
```

and immediately before the `finally:` block:

```python
        offenders = validate_isin_invariant(session)
        if offenders:
            print(f"WARNING: {len(offenders)} Indian companies still lack an ISIN: {offenders[:10]}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backfill_universe.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add backfill_universe.py tests/test_backfill_universe.py
git commit -m "feat: mark global companies and enforce the India-implies-ISIN invariant"
```

---

### Task 16: Full-universe ingest runbook

**Files:**
- Create: `backend/ingest_universe.py`
- Test: `tests/test_ingest_universe.py`

**Interfaces:**
- Consumes: everything from Phases 2-5.
- Produces: `run_ingest(root, day, session, fetch: bool = True, opener=None) -> dict`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest_universe.py`:

```python
import shutil
from datetime import date
from pathlib import Path

import ingest_universe
from app.models import Company, CompanyAlias, Listing

FIXTURES = Path(__file__).parent / "fixtures" / "universe" / "2026-08-03"


def test_ingest_from_an_existing_snapshot(tmp_path, db_session):
    destination = tmp_path / "2026-08-03"
    shutil.copytree(FIXTURES, destination)

    result = ingest_universe.run_ingest(
        str(tmp_path), date(2026, 8, 3), db_session, fetch=False,
    )

    # NSE contributes 3 ISINs, BSE contributes 4 of which the INF ETF row is
    # excluded, and RELIANCE is shared -> 5 distinct companies, 6 listings.
    assert result["created"] == 5
    assert db_session.query(Company).count() == 5
    # Reliance is dual-listed: one company, two listings.
    reliance = db_session.query(Company).filter_by(isin="INE002A01018").one()
    assert len(reliance.listings) == 2
    assert db_session.query(Listing).count() == 6
    assert db_session.query(CompanyAlias).count() > 0


def test_ingest_is_idempotent(tmp_path, db_session):
    shutil.copytree(FIXTURES, tmp_path / "2026-08-03")
    ingest_universe.run_ingest(str(tmp_path), date(2026, 8, 3), db_session, fetch=False)
    second = ingest_universe.run_ingest(str(tmp_path), date(2026, 8, 3), db_session, fetch=False)
    assert second["created"] == 0
    assert db_session.query(Company).count() == 5


def test_missing_snapshot_raises_rather_than_ingesting_nothing(tmp_path, db_session):
    try:
        ingest_universe.run_ingest(str(tmp_path), date(2026, 8, 3), db_session, fetch=False)
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError for a missing snapshot")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ingest_universe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ingest_universe'`

- [ ] **Step 3: Implement**

Create `backend/ingest_universe.py`:

```python
"""Full-universe ingest runbook (spec §4).

    python ingest_universe.py            # fetch a fresh snapshot, then load
    python ingest_universe.py --no-fetch # load the latest snapshot on disk

The BSE detail pass is ~5,000 throttled requests (30-40 minutes) and is
resumable: rerunning after an interruption skips whatever is already on
disk. The masters are 2 requests and are cheap to refetch daily.
"""
import argparse
from datetime import date

from sqlalchemy.orm import Session

from app.companies.matching import aliases
from app.companies.universe import fetchers, loader, normalize, snapshot
from app.db import SessionLocal


def run_ingest(root: str, day: date, session: Session, fetch: bool = True, opener=None) -> dict:
    if fetch:
        fetchers.fetch_nse_equity_list(root, day, opener=opener)
        fetchers.fetch_bse_scrip_list(root, day, opener=opener)

    nse_path = snapshot.master_path(root, day, "nse_equity_l.csv")
    bse_path = snapshot.master_path(root, day, "bse_scrips.json")
    if not nse_path.exists() or not bse_path.exists():
        raise FileNotFoundError(f"snapshot for {day.isoformat()} is incomplete under {root}")

    nse_rows = normalize.parse_nse_rows(nse_path.read_text(encoding="utf-8"))
    bse_rows = normalize.parse_bse_rows(bse_path.read_text(encoding="utf-8"))

    if fetch:
        scrip_codes = [(r.get("SCRIP_CD") or "").strip() for r in bse_rows]
        detail_result = fetchers.fetch_bse_details(
            root, day, [c for c in scrip_codes if c], opener=opener,
        )
        print(
            f"detail: fetched={detail_result['fetched']} "
            f"skipped={detail_result['skipped']} failed={len(detail_result['failed'])}"
        )
        if detail_result["failed"]:
            # Never silent: these companies land with NULL classification.
            print(f"  no classification for {len(detail_result['failed'])} scrips")

    detail_dir = snapshot.snapshot_dir(root, day) / snapshot.DETAIL_DIRNAME
    details = {
        p.stem: normalize.parse_bse_detail(p.read_text(encoding="utf-8"))
        for p in detail_dir.glob("*.json")
    } if detail_dir.is_dir() else {}

    records = normalize.build_records(nse_rows, bse_rows, details, day)
    result = loader.upsert_records(session, records)
    result["aliases"] = aliases.rebuild_aliases(session)
    result["records"] = len(records)
    if result["skipped"]:
        print(f"skipped {len(result['skipped'])} records: {result['skipped'][:10]}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-fetch", action="store_true", help="load the latest snapshot on disk")
    args = parser.parse_args()

    root = snapshot.DEFAULT_ROOT
    day = snapshot.latest_snapshot_day(root) if args.no_fetch else date.today()
    if day is None:
        raise SystemExit(f"no snapshot found under {root}")

    session = SessionLocal()
    try:
        print(run_ingest(root, day, session, fetch=not args.no_fetch))
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ingest_universe.py -v`
Expected: 3 passed

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: no failures.

- [ ] **Step 6: Commit**

```bash
git add ingest_universe.py tests/test_ingest_universe.py
git commit -m "feat: full-universe ingest runbook with resumable detail pass"
```

---

### Task 17: AMFI spike and conditional loader

**Files:**
- Modify: `app/companies/universe/fetchers.py`
- Modify: `app/companies/universe/loader.py`
- Test: `tests/test_universe_amfi.py`

**Interfaces:**
- Consumes: `Company.isin`.
- Produces: `parse_amfi_rows(csv_text: str) -> list[dict]`, `apply_amfi_categorisation(session, rows, as_of) -> int`.

**This task is timeboxed to 30 minutes of searching.** The documented AMFI URL returned 404 on 2026-08-03. If the current file cannot be located, implement the parser and loader against the documented CSV shape, leave `amfi_tier` NULL in production, and record the outcome. Everything else already works without it.

- [ ] **Step 1: Spike — locate the file (30 min box)**

Try, in order:
1. `https://www.amfiindia.com/research-information/other-data` — look for a categorisation link.
2. Search for `site:amfiindia.com "average market capitalisation" categorisation`.
3. Check the SEBI circular that mandates the list for the canonical location.

Record the outcome in the commit message either way. If found, save a copy to `data/universe/<day>/amfi_categorisation.csv` and note the real column names — **the parser below assumes `Company Name`, `ISIN`, `Average Market Cap`, `Categorization`, and must be corrected to match the actual file before Step 3.**

- [ ] **Step 2: Write the failing test**

Create `tests/test_universe_amfi.py`:

```python
from datetime import date

from app.companies.universe import loader, normalize
from app.models import Company

AS_OF = date(2026, 8, 3)

CSV = """Company Name,ISIN,Average Market Cap,Categorization
Reliance Industries Limited,INE002A01018,1750000.00,Large Cap
Some Mid Co Limited,INE111Z01010,45000.00,Mid Cap
Some Small Co Limited,INE222Z01011,900.00,Small Cap
"""


def test_parse_amfi_rows_normalizes_the_tier_vocabulary():
    rows = normalize.parse_amfi_rows(CSV)
    assert [r["amfi_tier"] for r in rows] == ["LARGE", "MID", "SMALL"]
    assert rows[0]["isin"] == "INE002A01018"
    assert rows[0]["amfi_rank"] == 1


def test_apply_amfi_sets_tier_rank_and_as_of(db_session):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries Limited", sector="oil_gas",
        index_tier="NIFTY50", isin="INE002A01018",
    ))
    db_session.commit()

    updated = loader.apply_amfi_categorisation(db_session, normalize.parse_amfi_rows(CSV), AS_OF)
    assert updated == 1
    company = db_session.query(Company).one()
    assert company.amfi_tier == "LARGE"
    assert company.amfi_rank == 1
    assert company.amfi_as_of == AS_OF


def test_unknown_isin_is_ignored_not_created(db_session):
    updated = loader.apply_amfi_categorisation(db_session, normalize.parse_amfi_rows(CSV), AS_OF)
    assert updated == 0
    assert db_session.query(Company).count() == 0
```

- [ ] **Step 3: Implement the parser**

Append to `app/companies/universe/normalize.py`:

```python
_AMFI_TIER_VOCABULARY = {
    "large cap": "LARGE", "largecap": "LARGE",
    "mid cap": "MID", "midcap": "MID",
    "small cap": "SMALL", "smallcap": "SMALL",
}


def parse_amfi_rows(csv_text: str) -> list[dict]:
    """AMFI's half-yearly categorisation list -- the only PUBLISHED source
    for the regulatory LARGE/MID/SMALL split. Rank is the row's position in
    the file, which AMFI publishes in descending average-market-cap order.

    Rows whose tier is outside the published vocabulary are dropped rather
    than guessed at.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []
    for position, raw in enumerate(reader, start=1):
        row = {(k or "").strip(): _clean(v) for k, v in raw.items()}
        isin = row.get("ISIN", "").upper()
        tier = _AMFI_TIER_VOCABULARY.get(row.get("Categorization", "").lower())
        if not is_company_isin(isin) or tier is None:
            continue
        rows.append({"isin": isin, "amfi_tier": tier, "amfi_rank": position})
    return rows
```

- [ ] **Step 4: Implement the loader**

Append to `app/companies/universe/loader.py`:

```python
def apply_amfi_categorisation(session: Session, rows: list[dict], as_of) -> int:
    """Write AMFI's published tier onto companies matched by ISIN.

    Never creates a company: AMFI's list is a categorisation of the
    universe, not a source for it. An ISIN we don't hold is skipped.
    """
    updated = 0
    for row in rows:
        company = session.query(Company).filter_by(isin=row["isin"]).one_or_none()
        if company is None:
            continue
        company.amfi_tier = row["amfi_tier"]
        company.amfi_rank = row["amfi_rank"]
        company.amfi_as_of = as_of
        updated += 1
    session.commit()
    return updated
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_universe_amfi.py -v`
Expected: 3 passed

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: no failures.

- [ ] **Step 7: Commit**

```bash
git add app/companies/universe/normalize.py app/companies/universe/loader.py tests/test_universe_amfi.py
git commit -m "feat: AMFI categorisation parser and loader

Spike outcome: <FOUND at <url> | NOT FOUND after 30min — amfi_tier stays
NULL in production and every company falls back to the derived tier>"
```

---

### Task 18: Label the yfinance market-cap fallback

**Files:**
- Modify: `app/companies/market_caps.py:33-48` (`refresh_market_caps`)
- Test: `tests/test_market_caps.py`

**Interfaces:**
- Consumes: `config.MARKET_CAP_MAX_AGE_DAYS`.
- Produces: `refresh_market_caps(session, tickers, today: date | None = None) -> int` — unchanged signature plus an optional `today` for testing.

Spec §6.2: yfinance is a labelled fallback, never the primary, and must never overwrite an exchange-published value.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_market_caps.py` (create the file if absent, with `from app.companies import market_caps` and `from app.models import Company` at the top):

```python
from datetime import date, timedelta

TODAY = date(2026, 8, 3)


def test_yfinance_cap_is_labelled(db_session, monkeypatch):
    db_session.add(Company(
        ticker="NSEONLY.NS", name="NSE Only Ltd", sector="other", index_tier="OTHER",
    ))
    db_session.commit()
    monkeypatch.setattr(market_caps, "fetch_market_cap", lambda _t: 1234.0)

    market_caps.refresh_market_caps(db_session, ["NSEONLY.NS"], today=TODAY)
    company = db_session.query(Company).one()
    assert company.market_cap == 1234.0
    assert company.market_cap_source == "yfinance"
    assert company.market_cap_as_of == TODAY


def test_yfinance_never_overwrites_a_fresh_exchange_cap(db_session, monkeypatch):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries Limited", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1750000.0, market_cap_source="BSE",
        market_cap_as_of=TODAY,
    ))
    db_session.commit()
    monkeypatch.setattr(market_caps, "fetch_market_cap", lambda _t: 1.0)

    market_caps.refresh_market_caps(db_session, ["RELIANCE.NS"], today=TODAY)
    company = db_session.query(Company).one()
    assert company.market_cap == 1750000.0
    assert company.market_cap_source == "BSE"


def test_yfinance_does_replace_a_stale_exchange_cap(db_session, monkeypatch):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries Limited", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1750000.0, market_cap_source="BSE",
        market_cap_as_of=TODAY - timedelta(days=400),
    ))
    db_session.commit()
    monkeypatch.setattr(market_caps, "fetch_market_cap", lambda _t: 9.0)

    market_caps.refresh_market_caps(db_session, ["RELIANCE.NS"], today=TODAY)
    company = db_session.query(Company).one()
    assert company.market_cap == 9.0
    assert company.market_cap_source == "yfinance"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_market_caps.py -v`
Expected: FAIL — `TypeError: refresh_market_caps() got an unexpected keyword argument 'today'`

- [ ] **Step 3: Implement**

Replace `refresh_market_caps` in `app/companies/market_caps.py`:

```python
def refresh_market_caps(session: Session, tickers: list[str], today: date | None = None) -> int:
    """Fetch + persist market caps for ``tickers``. Returns how many
    companies were updated. A failed fetch keeps the previous value (a
    stale cap beats a nulled-out tier).

    yfinance is the FALLBACK source (spec §6.2). The primary is BSE's
    published Mktcap, loaded in bulk by the universe ingest. A fresh
    exchange-published cap is never overwritten by a scraped one -- only a
    stale one is, and the replacement is labelled so
    app.market.cap_tier.resolve_cap_tier can report where the number came
    from.
    """
    today = today or date.today()
    updated = 0
    for ticker in tickers:
        company = session.query(Company).filter_by(ticker=ticker).one_or_none()
        if company is None:
            continue
        if (
            company.market_cap_source == "BSE"
            and company.market_cap_as_of is not None
            and (today - company.market_cap_as_of).days <= config.MARKET_CAP_MAX_AGE_DAYS
        ):
            continue
        cap = fetch_market_cap(ticker)
        if cap is None:
            continue
        company.market_cap = cap
        company.market_cap_source = "yfinance"
        company.market_cap_as_of = today
        session.commit()
        updated += 1
    return updated
```

Add to the imports at the top of the file:

```python
from datetime import date

from app import config
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_market_caps.py -v`
Expected: 3 passed

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: no failures.

- [ ] **Step 6: Commit**

```bash
git add app/companies/market_caps.py tests/test_market_caps.py
git commit -m "feat: label yfinance caps as fallback, never overwrite fresh exchange caps"
```

---

### Task 19: Wire cap-tier resolution into its consumers

**Files:**
- Modify: `app/market/cap_tier.py`
- Modify: `app/market/ripple.py:64`
- Modify: `app/market/discovery.py:45-47`
- Modify: `app/market/ripple_layers.py:105-108`
- Test: `tests/test_cap_tier.py`

**Interfaces:**
- Consumes: `resolve_cap_tier`, `CapTier`.
- Produces: `cap_tier_map(session, today: date | None = None) -> dict[str, str]` — the batch equivalent, staleness- and market-aware.

Without this task `resolve_cap_tier` exists but nothing calls it, and the staleness rule from spec §6.3 is never enforced on a real read path.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cap_tier.py`:

```python
from app.market.cap_tier import cap_tier_map


def test_cap_tier_map_excludes_stale_caps(db_session):
    db_session.add(Company(
        ticker="FRESH.NS", name="Fresh Ltd", sector="other", index_tier="OTHER",
        market_cap=1000.0, market_cap_source="BSE", market_cap_as_of=TODAY,
    ))
    db_session.add(Company(
        ticker="STALE.NS", name="Stale Ltd", sector="other", index_tier="OTHER",
        market_cap=2000.0, market_cap_source="BSE",
        market_cap_as_of=TODAY - timedelta(days=400),
    ))
    db_session.commit()

    tiers = cap_tier_map(db_session, today=TODAY)
    assert tiers == {"FRESH.NS": "LARGE"}


def test_cap_tier_map_excludes_global_companies(db_session):
    db_session.add(Company(
        ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP",
        market="GLOBAL", market_cap=3000000.0, market_cap_source="yfinance",
        market_cap_as_of=TODAY,
    ))
    db_session.commit()
    assert cap_tier_map(db_session, today=TODAY) == {}


def test_cap_tier_map_prefers_published_amfi_tier(db_session):
    db_session.add(Company(
        ticker="BIG.NS", name="Big Ltd", sector="other", index_tier="OTHER",
        market_cap=9000.0, market_cap_source="BSE", market_cap_as_of=TODAY,
        amfi_tier="MID", amfi_rank=120, amfi_as_of=TODAY,
    ))
    db_session.commit()
    # Rank 1 by cap would be LARGE; AMFI's published MID wins.
    assert cap_tier_map(db_session, today=TODAY) == {"BIG.NS": "MID"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cap_tier.py -k cap_tier_map -v`
Expected: FAIL — `ImportError: cannot import name 'cap_tier_map'`

- [ ] **Step 3: Implement the batch map**

Append to `app/market/cap_tier.py`:

```python
def cap_tier_map(session: Session, today: date | None = None) -> dict[str, str]:
    """{ticker: tier} for every Indian company with a fresh market cap.

    The batch counterpart to resolve_cap_tier, for callers that tag many
    companies at once (app.market.discovery, app.market.ripple_layers).
    Applies the same precedence and the same staleness rule -- a ticker
    absent from the result has no honest tier and must render as "no data",
    never as a default bucket.
    """
    today = today or date.today()
    companies = (
        session.query(Company)
        .filter(Company.market == "INDIA")
        .filter(Company.market_cap.isnot(None))
        .all()
    )
    fresh = [
        c for c in companies
        if not _is_stale(c.market_cap_as_of, config.MARKET_CAP_MAX_AGE_DAYS, today)
    ]
    derived = compute_cap_tiers([(c.ticker, c.market_cap) for c in fresh])

    tiers: dict[str, str] = {}
    for company in fresh:
        base = derived.get(company.ticker)
        if base is None:
            continue
        amfi_fresh = (
            company.amfi_tier
            and not _is_stale(company.amfi_as_of, config.AMFI_MAX_AGE_DAYS, today)
        )
        if not amfi_fresh:
            tiers[company.ticker] = base
        elif company.amfi_tier == "SMALL" and base == "MICRO":
            tiers[company.ticker] = "MICRO"
        else:
            tiers[company.ticker] = company.amfi_tier
    return tiers
```

- [ ] **Step 4: Swap the three consumers**

In `app/market/discovery.py`, replace `_cap_tiers` (lines 45-47):

```python
def _cap_tiers(session: Session) -> dict[str, str]:
    # Staleness- and market-aware (spec §6.3): a company whose cap is too
    # old to rank honestly is absent from the map and renders as no-data.
    return cap_tier_map(session)
```

and change its import at line 16 to `from app.market.cap_tier import cap_tier_map`.

In `app/market/ripple_layers.py`, replace lines 105-108 with:

```python
    cap_tiers = cap_tier_map(session)
```

and change its import at line 19 to `from app.market.cap_tier import cap_tier_map`.

In `app/market/ripple.py`, replace the `"cap_tier"` value at line 64 with:

```python
            "cap_tier": (resolved := resolve_cap_tier(session, company)) and resolved.tier,
```

and change its import at line 23 to `from app.market.cap_tier import resolve_cap_tier`.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_cap_tier.py tests/test_discovery.py tests/test_ripple_layers.py -v`
Expected: all pass. Tests that seed a `market_cap` without a `market_cap_as_of` will now get no tier — update those fixtures to set `market_cap_as_of` rather than relaxing the staleness rule.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: no failures.

- [ ] **Step 7: Commit**

```bash
git add app/market/cap_tier.py app/market/ripple.py app/market/discovery.py app/market/ripple_layers.py tests/test_cap_tier.py
git commit -m "feat: enforce cap-tier staleness and AMFI precedence on every read path"
```

---

### Task 20: Schedule the refresh cadences

**Files:**
- Modify: `app/scheduler.py:294-336`
- Test: `tests/test_scheduler_universe.py`

**Interfaces:**
- Consumes: `ingest_universe.run_ingest`, `fetchers`, `snapshot`.
- Produces: `_run_universe_master_refresh() -> None`, `_run_universe_detail_refresh() -> None`.

Spec §4 specifies daily masters, monthly per-scrip detail. Without this the universe only updates when someone runs the script by hand.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scheduler_universe.py`:

```python
import app.scheduler as scheduler


def test_master_refresh_never_raises(monkeypatch):
    def boom(*_a, **_kw):
        raise OSError("nse down")

    monkeypatch.setattr(scheduler.fetchers, "fetch_nse_equity_list", boom)
    # A dead exchange must not kill the scheduler thread -- same contract as
    # every other job in this module.
    scheduler._run_universe_master_refresh()


def test_detail_refresh_never_raises(monkeypatch):
    monkeypatch.setattr(
        scheduler.snapshot, "latest_snapshot_day", lambda _root: None,
    )
    scheduler._run_universe_detail_refresh()


def test_jobs_are_registered():
    import inspect
    source = inspect.getsource(scheduler.start_scheduler)
    assert "universe_master_refresh" in source
    assert "universe_detail_refresh" in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scheduler_universe.py -v`
Expected: FAIL — `AttributeError: module 'app.scheduler' has no attribute 'fetchers'`

- [ ] **Step 3: Implement the jobs**

Add to the imports at the top of `app/scheduler.py`:

```python
from app.companies.universe import fetchers, snapshot
```

Add both job functions above `start_scheduler`:

```python
def _run_universe_master_refresh() -> None:
    """Daily: refetch both exchange masters and reload. Two requests.

    Detail fetching is deliberately NOT done here -- that is ~5,000
    requests and runs on its own monthly job. Never raises: an exchange
    outage must not kill the scheduler thread.
    """
    from datetime import date

    import ingest_universe

    try:
        today = date.today()
        fetchers.fetch_nse_equity_list(snapshot.DEFAULT_ROOT, today)
        fetchers.fetch_bse_scrip_list(snapshot.DEFAULT_ROOT, today)
        session = SessionLocal()
        try:
            result = ingest_universe.run_ingest(
                snapshot.DEFAULT_ROOT, today, session, fetch=False,
            )
            logger.info("[universe] master refresh: %s", result)
        finally:
            session.close()
    except Exception as exc:
        logger.warning("[universe] master refresh failed: %s", exc)


def _run_universe_detail_refresh() -> None:
    """Monthly: the ~5,000-request official-classification pass. Resumable,
    so an interrupted run continues from disk on the next firing."""
    try:
        day = snapshot.latest_snapshot_day(snapshot.DEFAULT_ROOT)
        if day is None:
            logger.warning("[universe] detail refresh skipped: no snapshot on disk")
            return
        from app.companies.universe import normalize

        bse_path = snapshot.master_path(snapshot.DEFAULT_ROOT, day, "bse_scrips.json")
        rows = normalize.parse_bse_rows(bse_path.read_text(encoding="utf-8"))
        codes = [(r.get("SCRIP_CD") or "").strip() for r in rows]
        result = fetchers.fetch_bse_details(
            snapshot.DEFAULT_ROOT, day, [c for c in codes if c],
        )
        logger.info("[universe] detail refresh: %s", result)
    except Exception as exc:
        logger.warning("[universe] detail refresh failed: %s", exc)
```

- [ ] **Step 4: Register the jobs**

In `start_scheduler`, immediately before `scheduler.start()`:

```python
    scheduler.add_job(
        _run_universe_master_refresh,
        trigger="interval",
        hours=24,
        id="universe_master_refresh",
    )
    scheduler.add_job(
        _run_universe_detail_refresh,
        trigger="interval",
        days=30,
        # Never at boot: this is ~5,000 throttled requests taking 30-40
        # minutes, and a restart loop would hammer BSE.
        next_run_time=datetime.now(timezone.utc) + timedelta(days=1),
        id="universe_detail_refresh",
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_scheduler_universe.py -v`
Expected: 3 passed

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: no failures.

- [ ] **Step 7: Commit**

```bash
git add app/scheduler.py tests/test_scheduler_universe.py
git commit -m "feat: schedule daily universe master refresh and monthly detail pass"
```

---

## Rollout Runbook

**AMENDED 2026-08-03 (final whole-branch review fix wave).** The version of
this runbook below the "on a database backup first" prose line was not
actually safe to run: there was no verified restore, no dry run of the
irreversible merge in step 3 (old numbering), no instruction to stop the
scheduler (which fires `_run_market_cap_refresh` 2 minutes after boot and
every 12 hours and WILL race the ingest), no ordering requirement for the
`market_cap` unit fix (CRITICAL 1 -- see `app/companies/universe/normalize.py`),
and step 6's "Verify" block only printed counts for a human to eyeball
rather than asserting on them. Read this whole section, in order, before
running anything.

```bash
cd backend

# 0. BACKUP FIRST, WITH A VERIFIED RESTORE. A backup that has never been
#    restored is not a backup -- confirm the dump is actually loadable
#    before you touch production data, using a throwaway target so the
#    restore test itself cannot corrupt anything.
pg_dump "$DATABASE_URL" -Fc -f /path/to/backup/newsflo-pre-cap-tiers.dump
createdb newsflo_restore_check
pg_restore -d newsflo_restore_check /path/to/backup/newsflo-pre-cap-tiers.dump
psql newsflo_restore_check -c "select count(*) from companies;"   # sanity: nonzero, matches prod
dropdb newsflo_restore_check
# (Local/dev SQLite: substitute a plain file copy of newsflo.db, then open
# the COPY with `sqlite3 copy.db "select count(*) from companies;"` as the
# equivalent restore-verification step -- never run this against the live
# newsflo.db file.)

# 1. STOP THE SCHEDULER for the entire migration window (steps 3-9 below).
#    _run_market_cap_refresh fires ~2 minutes after process boot and every
#    12 hours; if the app stays up while the backfill/ingest run, it can
#    interleave a yfinance-sourced market_cap write with the ingest's
#    BSE-sourced write for the same company mid-migration. Stop the app
#    process (or comment out the start_scheduler() call in app/main.py and
#    redeploy) now. Do not restart it until step 10 passes.

# 2. DEPLOY THE market_cap UNIT FIX BEFORE RUNNING ANYTHING BELOW.
#    CRITICAL 1 (this fix wave): BSE's Mktcap is Rs CRORE, yfinance's
#    fast_info["marketCap"] is ABSOLUTE RUPEES, and the two were being
#    written to the same Company.market_cap column unconverted. Every
#    cap-tier rank computed from a mixed-unit pool is wrong -- there is no
#    partial-credit ordering here. If this fix isn't already deployed,
#    deploy it now, before step 3.

# 3. Apply schema
python -c "from app.db import init_db; init_db(); print('schema ok')"

# 4. Fetch masters only (2 requests)
python -c "from datetime import date; from app.companies.universe import fetchers; \
  fetchers.fetch_nse_equity_list('data/universe', date.today()); \
  fetchers.fetch_bse_scrip_list('data/universe', date.today()); print('masters ok')"

# 5. DRY RUN the backfill FIRST. --dry-run runs the real pipeline
#    (corrections, the phantom-company merge with its per-table FK row
#    counts, globals marked, companies flagged SUSPENDED) far enough to
#    print exactly what it would do, and writes nothing (verified by
#    tests/test_backfill_universe.py::test_dry_run_leaves_the_database_byte_identical,
#    which hashes the on-disk file before/after). Read this output in full
#    before proceeding -- it is the last checkpoint before step 6's
#    irreversible delete.
python backfill_universe.py --dry-run

# 6. Adopt the existing 509 for real — does NOT grow the universe.
#    THIS STEP CONTAINS AN IRREVERSIBLE COMPANY MERGE
#    (merge_duplicate_companies deletes the phantom HPCL.NS/OILINDIA.NS
#    rows after reassigning their alert history to the canonical company).
#    This is why step 0's verified backup happens first, not "at some
#    point during rollout".
python backfill_universe.py

# 7. Regenerate the regression corpus against the corrected data, then gate
python export_match_corpus.py
python -m pytest tests/test_matching_gate.py -v

# 8. Full detail pass + ingest (30-40 min, resumable). DO NOT run this (or
#    any step in this runbook) with the matcher gate active across IST
#    midnight: tests/test_api.py::test_list_alerts_limits_to_the_most_recent_alerts
#    is a KNOWN PRE-EXISTING flake (unrelated to this branch -- the
#    /api/alerts endpoint windows to today's-IST alerts while the test
#    seeds 205 staggered backwards from `now`; crossing IST midnight drops
#    the oldest) that will look exactly like branch damage if it fires
#    mid-rollout and cost real time chasing a ghost.
python ingest_universe.py

# 9. AMFI categorisation (optional, additive -- IMPORTANT 2 in this fix
#    wave, Task 17 in this plan). AMFI publishes ONLY .xlsx and this
#    project deliberately has no openpyxl/pandas-excel dependency (see
#    load_amfi.py's module docstring for why). Manual step:
#      a. Download the current file from
#         https://portal.amfiindia.com/spages/AverageMarketCapitalization30Jun2026.xlsx
#         (re-check https://www.amfiindia.com/otherdata/categorisation-of-stocks
#         if that exact filename has rolled to a new half-year).
#      b. Open it in Excel/LibreOffice/Google Sheets and "Save As"/"Export"
#         CSV, keeping the header row exactly as published.
#      c. Save it under the current snapshot day, e.g.
#         data/universe/<day>/amfi_categorisation.csv, then:
python load_amfi.py data/universe/<day>/amfi_categorisation.csv

# 10. Verify — these are ASSERTIONS, not prints. The script aborts
#     (non-zero exit, AssertionError) if any actual count deviates from
#     its expected value by more than 5%, instead of leaving a human to
#     eyeball five printed numbers and miss a regression.
python -c "
from app.db import SessionLocal
from app.models import Company, Listing
s = SessionLocal()
counts = {
    'companies': s.query(Company).count(),
    'india': s.query(Company).filter_by(market='INDIA').count(),
    'listings': s.query(Listing).count(),
    'with cap': s.query(Company).filter(Company.market_cap.isnot(None)).count(),
    'classified': s.query(Company).filter(Company.official_sector.isnot(None)).count(),
}
expected = {'companies': 5470, 'india': 4967, 'listings': 7200, 'with cap': 4800, 'classified': 4835}
TOLERANCE = 0.05
failures = []
for key, actual in counts.items():
    exp = expected[key]
    deviation = abs(actual - exp) / exp
    status = 'OK' if deviation <= TOLERANCE else 'FAIL'
    print(f'{key}: {actual} (expected ~{exp}, deviation {deviation:.1%}) [{status}]')
    if deviation > TOLERANCE:
        failures.append(key)
assert not failures, f'counts deviated beyond {TOLERANCE:.0%} tolerance: {failures} -- ABORT, do not restart the scheduler, investigate against the step 0 backup'
print('all counts within tolerance')
"

# 11. Only once step 10's assertions pass: restart the scheduler (redeploy
#     the app / restore the start_scheduler() call from step 1).
```

Expected after step 10: ~5,470 companies (~4,967 Indian + 507 global), ~7,200 listings, ~4,800 with a market cap, ~4,835 classified.

### Rollback notes

- **`USE_ALIAS_MATCHER=false` rolls back the matcher ONLY** (Task 12's swap
  of resolution onto the new name-matching ladder). It does NOT undo the
  ingest (Tasks 6-16), does NOT restore the phantom HPCL.NS/OILINDIA.NS
  rows deleted by step 6's merge, and does NOT reverse the fan-out
  reordering from Task 12. If something goes wrong after step 3, the only
  way back is the verified backup from step 0 -- the flag is a matcher
  kill switch, not a migration undo button.
- **Re-running `seed_nifty_indices.py` after this rollout silently
  overwrites `sector` and `name`** for roughly 500 companies, via the old
  keyword-based `SECTOR_MAP` in `app/companies/loader.py` -- clobbering the
  official BSE/AMFI-sourced classification this rollout just landed for
  those companies. Do not run it as routine maintenance after this
  rollout. If it must run for a genuinely new reason (e.g. picking up a new
  Nifty index membership), re-run `ingest_universe.py` immediately
  afterwards to restore official classification over its keyword guesses.

**Rollback:** set `USE_ALIAS_MATCHER=false` to restore the previous resolver without a deploy. The ingested rows are additive and harmless with the legacy matcher, though sector fan-out will already be using market-cap ordering (that change is not behind the flag — revert Task 12's query change if it must be undone).
