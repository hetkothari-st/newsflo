# Nifty Index Company Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate `companies` with every company across all 27 Nifty index lists (broad-market cap tiers + sectoral + strategy), tagged with full index membership, and expose an `isin` + `logo_url` per company via the API.

**Architecture:** Static seed data (`nifty_indices_seed.py`, already compiled from live official NSE CSVs) is upserted into `companies` (with a new `isin` column) and a new `company_index_memberships` join table via a loader function, run once by a standalone script against the existing `newsflo.db`. `resolution.py`'s tier ranking is extended for the new cap tiers. Logo is computed at API-response time from `isin`/`ticker`, no new stored column for it.

**Tech Stack:** Python, SQLAlchemy, FastAPI, pytest, TypeScript/React frontend.

## Global Constraints

- Follow the existing upsert pattern (query-before-insert, no reliance on catching unique-constraint errors) — see `load_companies_from_csv` / `load_global_companies`.
- No Alembic in this project — new columns go through `db.py`'s guarded `_ADDED_COLUMNS` `ALTER TABLE` list.
- `backend/app/companies/nifty_indices_seed.py` already exists with `CAP_TIER_COMPANIES`, `EXTRA_COMPANIES`, `INDEX_MEMBERSHIPS` (507 companies, 27 index codes, verified: 0 missing symbols, 0 cross-tier duplicates) — do not regenerate it.

---

### Task 1: Schema — `isin` column + `CompanyIndexMembership` table

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/db.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `Company.isin` (nullable String); `CompanyIndexMembership(id, company_id, index_code, created_at)` with unique constraint on `(company_id, index_code)`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_models.py`:

```python
def test_company_isin_column(db_session):
    company = Company(
        ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1_800_000.0, isin="INE002A01018",
    )
    db_session.add(company)
    db_session.commit()

    fetched = db_session.query(Company).filter_by(ticker="RELIANCE.NS").one()
    assert fetched.isin == "INE002A01018"


def test_company_index_membership(db_session):
    company = Company(
        ticker="HDFCBANK.NS", name="HDFC Bank", sector="banking",
        index_tier="NIFTY50", market_cap=1_000_000.0,
    )
    db_session.add(company)
    db_session.commit()

    from app.models import CompanyIndexMembership
    db_session.add(CompanyIndexMembership(company_id=company.id, index_code="NIFTYBANK"))
    db_session.add(CompanyIndexMembership(company_id=company.id, index_code="NIFTY50"))
    db_session.commit()

    rows = db_session.query(CompanyIndexMembership).filter_by(company_id=company.id).all()
    assert {r.index_code for r in rows} == {"NIFTYBANK", "NIFTY50"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: FAIL with `TypeError: 'isin' is an invalid keyword argument for Company` (and `ImportError: cannot import name 'CompanyIndexMembership'`)

- [ ] **Step 3: Add the column and table**

In `backend/app/models.py`, inside `class Company`, after the `market_cap` line:

```python
    market_cap = Column(Float, nullable=True)
    isin = Column(String, nullable=True, unique=True)
```

After the `Company` class (before `class Article`), add a new class:

```python
class CompanyIndexMembership(Base):
    __tablename__ = "company_index_memberships"
    __table_args__ = (UniqueConstraint("company_id", "index_code", name="uq_company_index"),)

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    index_code = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    company = relationship("Company")
```

In `backend/app/db.py`, add to `_ADDED_COLUMNS`:

```python
_ADDED_COLUMNS = [
    ("articles", "image_url", "VARCHAR"),
    ("alert_companies", "key_points_json", "TEXT"),
    ("companies", "isin", "VARCHAR"),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/db.py backend/tests/test_models.py
git commit -m "Add isin column and company_index_memberships table"
```

---

### Task 2: Loader — `load_nifty_indices`

**Files:**
- Create: `backend/app/companies/nifty_loader.py`
- Test: `backend/tests/test_nifty_loader.py`

**Interfaces:**
- Consumes: `CAP_TIER_COMPANIES`, `EXTRA_COMPANIES`, `INDEX_MEMBERSHIPS` from `app.companies.nifty_indices_seed`; `Company`, `CompanyIndexMembership` from `app.models`; `_normalize_sector` from `app.companies.loader`.
- Produces: `load_nifty_indices(session: Session) -> dict` returning `{"companies": int, "memberships": int}`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_nifty_loader.py`:

```python
from app.companies.nifty_loader import load_nifty_indices
from app.models import Company, CompanyIndexMembership


def test_load_nifty_indices_creates_companies_and_memberships(db_session):
    load_nifty_indices(db_session)

    reliance = db_session.query(Company).filter_by(ticker="RELIANCE.NS").one()
    assert reliance.index_tier == "NIFTY50"
    assert reliance.isin == "INE002A01018"
    assert reliance.sector == "oil_gas"

    memberships = {
        m.index_code
        for m in db_session.query(CompanyIndexMembership).filter_by(company_id=reliance.id).all()
    }
    assert "NIFTY50" in memberships
    assert "NIFTY100" in memberships
    assert "NIFTY500" in memberships
    assert "NIFTYINFRA" in memberships


def test_load_nifty_indices_tags_extra_companies_as_other(db_session):
    load_nifty_indices(db_session)

    psb = db_session.query(Company).filter_by(ticker="PSB.NS").one()
    assert psb.index_tier == "OTHER"
    memberships = {
        m.index_code
        for m in db_session.query(CompanyIndexMembership).filter_by(company_id=psb.id).all()
    }
    assert memberships == {"NIFTYPSUBANK"}


def test_load_nifty_indices_is_idempotent(db_session):
    first = load_nifty_indices(db_session)
    second = load_nifty_indices(db_session)

    assert first["companies"] == second["companies"]
    assert first["memberships"] == second["memberships"]
    assert db_session.query(Company).filter_by(ticker="RELIANCE.NS").count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_nifty_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.nifty_loader'`

- [ ] **Step 3: Write the loader**

Create `backend/app/companies/nifty_loader.py`:

```python
from sqlalchemy.orm import Session

from app.companies.loader import _normalize_sector
from app.companies.nifty_indices_seed import CAP_TIER_COMPANIES, EXTRA_COMPANIES, INDEX_MEMBERSHIPS
from app.models import Company, CompanyIndexMembership

# Membership rows for these two are cross-checked directly against NSE's own
# ind_nifty100list.csv / ind_nifty500list.csv, not derived from the four cap
# tiers, so they are recorded exactly like every other index code.
_CAP_TIER_CODES = {"NIFTY50", "NIFTYNEXT50", "NIFTYMIDCAP150", "NIFTYSMALLCAP250"}


def _upsert_company(session: Session, ticker: str, name: str, industry: str, isin: str, index_tier: str) -> Company:
    sector = _normalize_sector(industry)
    existing = session.query(Company).filter_by(ticker=ticker).one_or_none()
    if existing:
        existing.name = name
        existing.sector = sector
        existing.isin = isin
        if index_tier in _CAP_TIER_CODES or existing.index_tier is None:
            existing.index_tier = index_tier
        return existing
    company = Company(ticker=ticker, name=name, sector=sector, index_tier=index_tier, isin=isin, market_cap=None)
    session.add(company)
    session.flush()
    return company


def _add_membership(session: Session, company_id: int, index_code: str) -> bool:
    existing = (
        session.query(CompanyIndexMembership)
        .filter_by(company_id=company_id, index_code=index_code)
        .one_or_none()
    )
    if existing:
        return False
    session.add(CompanyIndexMembership(company_id=company_id, index_code=index_code))
    return True


def load_nifty_indices(session: Session) -> dict:
    """Upsert every company from every Nifty index seed list, and record
    full index membership (a company can be in many indices at once).

    Cap-tier indices (NIFTY50/NIFTYNEXT50/NIFTYMIDCAP150/NIFTYSMALLCAP250)
    additionally set Company.index_tier -- the single "broadest tier" used
    by resolution.py's sector-inference ranking. Every other index only
    adds a CompanyIndexMembership row. EXTRA_COMPANIES (sectoral-only,
    outside the Nifty 500 cap-tier universe) get index_tier="OTHER".
    """
    ticker_by_symbol: dict[str, str] = {}
    company_count = 0

    for tier, rows in CAP_TIER_COMPANIES.items():
        for row in rows:
            symbol = row["ticker"][:-3]  # strip ".NS"
            ticker_by_symbol[symbol] = row["ticker"]
            _upsert_company(session, row["ticker"], row["name"], row["industry"], row["isin"], tier)
            company_count += 1

    for row in EXTRA_COMPANIES:
        symbol = row["ticker"][:-3]
        ticker_by_symbol[symbol] = row["ticker"]
        _upsert_company(session, row["ticker"], row["name"], row["industry"], row["isin"], "OTHER")
        company_count += 1

    membership_count = 0
    for index_code, symbols in INDEX_MEMBERSHIPS.items():
        for symbol in symbols:
            ticker = ticker_by_symbol.get(symbol)
            if ticker is None:
                continue
            company = session.query(Company).filter_by(ticker=ticker).one()
            if _add_membership(session, company.id, index_code):
                membership_count += 1

    session.commit()
    return {"companies": company_count, "memberships": membership_count}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_nifty_loader.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/nifty_loader.py backend/tests/test_nifty_loader.py
git commit -m "Add loader for full Nifty index company database"
```

---

### Task 3: `resolution.py` tier ranking

**Files:**
- Modify: `backend/app/companies/resolution.py:12-17`
- Test: `backend/tests/test_resolution.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_TIER_RANK` now ranks `NIFTY50` < `NIFTYNEXT50` < `NIFTYMIDCAP150` < `NIFTYSMALLCAP250` < else.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_resolution.py`:

```python
def test_tier_rank_prefers_niftynext50_over_midcap150(db_session):
    from app.companies.resolution import resolve_companies
    from app.analysis.schemas import CompanyMention

    next50 = _make_company(db_session, "NEXT50CO.NS", "Next50 Co", "oil_gas", None, index_tier="NIFTYNEXT50")
    midcap = _make_company(db_session, "MIDCO.NS", "Mid Co", "oil_gas", None, index_tier="NIFTYMIDCAP150")

    mention = CompanyMention(
        is_direct=False, sector="oil_gas", ticker=None, name=None,
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0,
        rationale="r", key_points=[],
    )
    resolved = resolve_companies(db_session, [mention])
    resolved_ids = [r["company_id"] for r in resolved]

    assert resolved_ids.index(next50.id) < resolved_ids.index(midcap.id)
```

(This mirrors the existing `test_resolution.py` fixtures — `_make_company` and `CompanyMention` are already defined/imported there; check the file's existing test for the exact `CompanyMention` field list before running, since some fields may differ.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_resolution.py -v`
Expected: FAIL — `next50` and `midcap` both rank at `else_=3` currently, so ordering is by ticker, not tier (test asserts tier ordering, which doesn't hold yet since `NIFTYNEXT50` isn't in `_TIER_RANK` before this fix)

- [ ] **Step 3: Update `_TIER_RANK`**

In `backend/app/companies/resolution.py`, replace:

```python
_TIER_RANK = case(
    (Company.index_tier == "NIFTY50", 0),
    (Company.index_tier == "NIFTY100", 1),
    (Company.index_tier == "NIFTY500", 2),
    else_=3,
)
```

with:

```python
_TIER_RANK = case(
    (Company.index_tier == "NIFTY50", 0),
    (Company.index_tier == "NIFTYNEXT50", 1),
    (Company.index_tier == "NIFTYMIDCAP150", 2),
    (Company.index_tier == "NIFTYSMALLCAP250", 3),
    else_=4,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_resolution.py -v`
Expected: PASS (all tests, including pre-existing ones — the old `NIFTY100`/`NIFTY500` tier values no longer rank specially, but no existing test asserts on those literal tier strings ranking above `else_`; confirm by reading test output)

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/resolution.py backend/tests/test_resolution.py
git commit -m "Rank new cap-tier values in sector-inference resolution"
```

---

### Task 4: Migration script + run against `newsflo.db`

**Files:**
- Create: `backend/seed_nifty_indices.py`

**Interfaces:**
- Consumes: `load_nifty_indices` from Task 2.

- [ ] **Step 1: Write the script**

Create `backend/seed_nifty_indices.py` (same convention as `backend/demo_push.py` / `backend/backfill_images.py`):

```python
from app.companies.nifty_loader import load_nifty_indices
from app.db import SessionLocal, init_db

if __name__ == "__main__":
    init_db()
    session = SessionLocal()
    try:
        result = load_nifty_indices(session)
        print(f"Upserted {result['companies']} companies, {result['memberships']} index memberships")
    finally:
        session.close()
```

- [ ] **Step 2: Run it against the real dev database**

Run: `cd backend && python seed_nifty_indices.py`
Expected output: `Upserted 507 companies, <N> index memberships` (N = total rows summed across all 27 `INDEX_MEMBERSHIPS` lists)

- [ ] **Step 3: Verify against the live DB**

Run:
```bash
cd backend && python -c "
import sqlite3
conn = sqlite3.connect('newsflo.db')
cur = conn.cursor()
cur.execute('SELECT index_tier, COUNT(*) FROM companies GROUP BY index_tier ORDER BY 2 DESC')
for row in cur.fetchall(): print(row)
cur.execute('SELECT COUNT(*) FROM company_index_memberships')
print('memberships', cur.fetchone())
"
```
Expected: `NIFTY50 50`, `NIFTYNEXT50 50`, `NIFTYMIDCAP150 150`, `NIFTYSMALLCAP250 250`, `GLOBAL_LARGE_CAP 500`, `OTHER 7` (the old generic `NIFTY100`/`NIFTY500` tier values should be gone, replaced by the four precise tiers)

- [ ] **Step 4: Commit**

```bash
git add backend/seed_nifty_indices.py
git commit -m "Add standalone script to seed the full Nifty index database"
```

---

### Task 5: Logos — Brandfetch config + API/frontend fields

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/routers/companies.py`
- Modify: `frontend/src/lib/api.ts`
- Test: `backend/tests/test_companies_api.py`

**Interfaces:**
- Produces: `settings.brandfetch_client_id: str` (empty default); `GET /api/companies` response items gain `"isin"` and `"logo_url"` keys; `Company` TS interface gains `isin: string | null` and `logo_url: string | null`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_companies_api.py`:

```python
def test_list_companies_includes_isin_and_logo_url(client, db_session):
    company = Company(
        ticker="RELIANCE.NS", name="Reliance", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0, isin="INE002A01018",
    )
    db_session.add(company)
    db_session.commit()

    res = client.get("/api/companies")
    body = res.json()
    row = next(c for c in body if c["ticker"] == "RELIANCE.NS")
    assert row["isin"] == "INE002A01018"
    assert row["logo_url"] is None  # BRANDFETCH_CLIENT_ID unset in test env
```

(Check the top of `test_companies_api.py` for the existing `client`/`db_session` fixture names before adding — reuse whatever's already imported there.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companies_api.py -v`
Expected: FAIL with `KeyError: 'isin'`

- [ ] **Step 3: Add the setting**

In `backend/app/config.py`, add to `Settings`:

```python
    brandfetch_client_id: str = os.environ.get("BRANDFETCH_CLIENT_ID", "")
```

- [ ] **Step 4: Update the router**

In `backend/app/routers/companies.py`, replace the `result.append(...)` block:

```python
from app.config import settings


def _logo_url(company: Company) -> str | None:
    if not settings.brandfetch_client_id:
        return None
    if company.isin:
        return f"https://cdn.brandfetch.io/{company.isin}?c={settings.brandfetch_client_id}"
    return f"https://cdn.brandfetch.io/ticker/{company.ticker}?c={settings.brandfetch_client_id}"
```

```python
        result.append({
            "id": c.id, "ticker": c.ticker, "name": c.name,
            "sector": c.sector, "index_tier": c.index_tier, "market": c_market,
            "isin": c.isin, "logo_url": _logo_url(c),
        })
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_companies_api.py -v`
Expected: PASS

- [ ] **Step 6: Update the frontend type**

In `frontend/src/lib/api.ts`, update the `Company` interface:

```typescript
export interface Company {
  id: number;
  ticker: string;
  name: string;
  sector: string;
  index_tier: string;
  market: 'IN' | 'GLOBAL';
  isin: string | null;
  logo_url: string | null;
}
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/config.py backend/app/routers/companies.py backend/tests/test_companies_api.py frontend/src/lib/api.ts
git commit -m "Expose isin and Brandfetch-derived logo_url from GET /api/companies"
```

---

### Task 6: Full backend test suite

- [ ] **Step 1: Run the full suite**

Run: `cd backend && python -m pytest -v`
Expected: all tests pass, including the pre-existing suite (no regressions from the `_TIER_RANK` or `Company` schema changes)

- [ ] **Step 2: Fix any regressions found**

If any pre-existing test hardcodes `index_tier="NIFTY100"` or `"NIFTY500"` and asserts on tier-ranking behavior specifically (not just as a label), update it to use `NIFTYNEXT50`/`NIFTYMIDCAP150` consistent with the new tier scheme. Do not change tests that just use `NIFTY50` as a generic fixture value — those are unaffected.

- [ ] **Step 3: Commit** (only if Step 2 required changes)

```bash
git add backend/tests/
git commit -m "Fix pre-existing tests for the new cap-tier scheme"
```
