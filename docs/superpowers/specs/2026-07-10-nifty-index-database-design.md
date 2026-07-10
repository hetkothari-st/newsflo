# Nifty Index Company Database — Design

## Goal

Extend the `companies` table so every company across all 25 Nifty indices (broad-market, sectoral, and strategy) is present, tagged with every index it belongs to, and carries a logo. This feeds the existing news → affected-companies pipeline (`resolution.py`), which currently only knows `NIFTY50` / `NIFTY100` / `NIFTY500` / `GLOBAL_LARGE_CAP` / `OTHER` as a single tier per company.

## Current state

- `companies` table: 1000 rows (500 Indian, tagged `NIFTY50`/`NIFTY100`/`NIFTY500`; 500 global, tagged `GLOBAL_LARGE_CAP`).
- `index_tier` is a single string column — cannot represent a company belonging to multiple indices at once (e.g. HDFC Bank is in Nifty50 **and** Nifty Bank **and** Nifty Financial Services simultaneously).
- No sectoral/strategy index data (Bank, IT, Pharma, FMCG, Auto, Realty, Media, PSU Bank, Private Bank, CPSE, PSE, ESG, India Consumption, Dividend Opportunities 50, Low Volatility, 200 Momentum 30, 50 Value 20, etc.) is tracked at all.
- No logo data.
- No seed script for the existing 1000 rows is checked into the repo — they were loaded via `app/companies/loader.py` / `app/companies/global_seed.py` outside of what's committed.

## Data source

NSE publishes official constituent lists at `https://archives.nseindia.com/content/indices/ind_<slug>list.csv` (verified working against `ind_nifty50list.csv` — content matches Wikipedia's current Nifty 50 list, columns: `Company Name, Industry, Symbol, Series, ISIN Code`).

This endpoint is bot-protected in a way that's fetchable via tooling available during this build, but **not** reliably fetchable from a plain server-side HTTP client at runtime. So: fetch all 25 lists now, bake the result into a static seed module — same pattern the codebase already uses for `global_seed.py` (a curated static `GLOBAL_COMPANIES` list, not a live API call).

### Index list and planned codes

| User-facing name | index_code | Tier type |
|---|---|---|
| Nifty 50 | `NIFTY50` | cap tier |
| Nifty Next 50 | `NIFTYNEXT50` | cap tier |
| Nifty Midcap 150 | `NIFTYMIDCAP150` | cap tier |
| Nifty Smallcap 250 | `NIFTYSMALLCAP250` | cap tier |
| Nifty 100 | `NIFTY100` | membership only (derived: NIFTY50 ∪ NIFTYNEXT50) |
| Nifty 500 | `NIFTY500` | membership only (derived: all 4 cap tiers) |
| Nifty Bank | `NIFTYBANK` | sectoral |
| Nifty Financial Services | `NIFTYFINSERVICE` | sectoral |
| Nifty PSU Bank | `NIFTYPSUBANK` | sectoral |
| Nifty Private Bank | `NIFTYPVTBANK` | sectoral |
| Nifty IT | `NIFTYIT` | sectoral |
| Nifty Pharma | `NIFTYPHARMA` | sectoral |
| Nifty Healthcare | `NIFTYHEALTHCARE` | sectoral |
| Nifty FMCG | `NIFTYFMCG` | sectoral |
| Nifty Auto | `NIFTYAUTO` | sectoral |
| Nifty Realty | `NIFTYREALTY` | sectoral |
| Nifty Media | `NIFTYMEDIA` | sectoral |
| Nifty Consumer Durables | `NIFTYCONSDURABLE` | sectoral |
| Nifty Infrastructure | `NIFTYINFRA` | sectoral |
| Nifty CPSE | `NIFTYCPSE` | thematic |
| Nifty PSE | `NIFTYPSE` | thematic |
| Nifty 100 ESG | `NIFTY100ESG` | strategy |
| Nifty India Consumption | `NIFTYCONSUMPTION` | thematic |
| Nifty Dividend Opportunities 50 | `NIFTYDIVOPP50` | strategy |
| Nifty Low Volatility (30 or 50 — verify exact NSE product name during fetch) | `NIFTYLOWVOL` | strategy |
| Nifty 200 Momentum 30 | `NIFTY200MOMENTUM30` | strategy |
| Nifty50 Value 20 | `NIFTY50VALUE20` | strategy |

`NIFTY100` and `NIFTY500` are not separate CSVs we need to load — they're derivable unions of the 4 cap-tier lists, but we'll still fetch NSE's own `ind_nifty100list.csv` / `ind_nifty500list.csv` as a cross-check against the union.

Exact slugs for the less obvious ones (ESG, CPSE/PSE, momentum/value/low-vol) get confirmed against the real NSE archive during implementation, not guessed here.

## Schema changes

`backend/app/models.py`:

```python
class Company(Base):
    ...
    isin = Column(String, nullable=True, unique=True)  # NSE ISIN; null for GLOBAL_LARGE_CAP rows


class CompanyIndexMembership(Base):
    __tablename__ = "company_index_memberships"
    __table_args__ = (UniqueConstraint("company_id", "index_code", name="uq_company_index"),)

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    index_code = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    company = relationship("Company")
```

`backend/app/db.py`: add `("companies", "isin", "VARCHAR")` to `_ADDED_COLUMNS` so the existing `newsflo.db` file gets the column via guarded `ALTER TABLE` (no Alembic in this project). `CompanyIndexMembership` table is picked up automatically by `Base.metadata.create_all`.

`index_tier` keeps its current meaning (single "broadest cap-tier a company sits in", used by `resolution.py`'s `_TIER_RANK` for sector-inference ranking) but becomes more precise: the 400 rows currently generically tagged `NIFTY500` split into their real `NIFTYNEXT50` / `NIFTYMIDCAP150` / `NIFTYSMALLCAP250` tiers.

`backend/app/companies/resolution.py`: `_TIER_RANK` gets the 3 new tier values:

```python
_TIER_RANK = case(
    (Company.index_tier == "NIFTY50", 0),
    (Company.index_tier == "NIFTYNEXT50", 1),
    (Company.index_tier == "NIFTYMIDCAP150", 2),
    (Company.index_tier == "NIFTYSMALLCAP250", 3),
    else_=4,
)
```

## Seed + loader

`backend/app/companies/nifty_indices_seed.py` — static data, one dict per index_code mapping to a list of `{"ticker", "name", "isin", "industry"}`, gathered by fetching all 25 NSE CSVs during this build (mirrors `global_seed.py`'s `GLOBAL_COMPANIES` pattern).

`backend/app/companies/nifty_loader.py`:

```python
def load_nifty_indices(session: Session) -> dict[str, int]:
    """Upsert every company from every Nifty index seed list, and record
    full index membership (a company can be in many indices at once).
    Cap-tier indices additionally set index_tier (the single "broadest
    tier" used by resolution.py's sector-inference ranking); all other
    indices only add a membership row.
    """
```

Same upsert-by-ticker pattern as `load_companies_from_csv` / `load_global_companies` (query-before-insert, no reliance on catching a unique-constraint error) — idempotent, safe to re-run.

`backend/seed_nifty_indices.py` — standalone runnable script (same convention as the existing `backend/demo_push.py` / `backend/backfill_images.py` root-level scripts) that opens a session and calls `load_nifty_indices`. This is how the existing 1000-row `newsflo.db` gets migrated in place.

## Logos

No logo file/URL stored per row. `Company.isin` is stored; logo is computed at API-response time:

- Indian companies (`isin` present): `https://cdn.brandfetch.io/{isin}?c={BRANDFETCH_CLIENT_ID}`
- Global companies (no ISIN): Brandfetch's ticker-route logo endpoint using `ticker`.
- `BRANDFETCH_CLIENT_ID` — new `Settings` field in `backend/app/config.py`, sourced from env var, empty by default. When empty, `logo_url` is `null` in API responses (no hard failure).

`GET /api/companies` (`backend/app/routers/companies.py`) response gains `isin` and `logo_url` fields. Frontend `Company` type in `frontend/src/lib/api.ts` gains the same two fields; no component wiring beyond the type/response — displaying the logo anywhere in the UI is out of scope for this spec.

## Out of scope

- Rendering logos anywhere in the frontend (AlertCard/AlertCover/etc.) — this spec only makes `logo_url` available via the API.
- Automatic periodic re-sync of index constituents (NSE reshuffles indices ~twice a year) — this is a one-time static seed; refreshing it later is a manual re-run of the same fetch process.
- Historical/point-in-time index membership — only current membership is tracked.
