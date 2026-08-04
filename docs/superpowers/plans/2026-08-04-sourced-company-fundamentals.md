# Sourced Company Fundamentals (Subsystem B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace LLM-invented business descriptions with exchange-published fact, and repair a sector-classification defect that currently leaves 65% of Indian companies as `other` in production.

**Architecture:** Extends the universe pipeline shipped 2026-08-04. No new fetching — the BSE payload already pulled monthly carries both the finer classification level we should have mapped and the financial ratios we currently discard.

**Spec:** `docs/superpowers/specs/2026-08-04-sourced-company-fundamentals-design.md`

## Global Constraints

- All commands run from `backend/`. `pytest.ini` sets `pythonpath = .`. Use `python -m pytest`.
- Baseline: **1022 tests passing** on `master` at `7529d1b`.
- **No Alembic.** New columns MUST be appended to `_ADDED_COLUMNS` in `app/db.py`.
- SQLAlchemy 2.0.35 — `session.get(Model, id)`, never legacy `Query.get()`.
- No test may make a network call.
- **Omit rather than fabricate.** An unmapped value yields `NULL`, never a guess. An absent ratio is `NULL`, never `0`.
- **Never clobber.** A refresh with no payload leaves stored values intact.
- Closed vocabularies: `sector` is the 18 values in `app.analysis.schemas.SECTORS`; `sub_sector` is the 72 values in `app.companies.sub_sectors.SUB_SECTOR_TAXONOMY`.
- Production is live and migrated. Scripts run there via `railway ssh --service newsflo-app`, from `/app`.

## Scope Note — why Phase 1 exists

This plan opens with a defect fix, not the feature. Measured in production 2026-08-04:

- 3,113 of 4,814 Indian companies have `sector='other'`; 2,971 of those carry a valid official classification.
- `sector_map.OFFICIAL_SECTOR_TO_BUCKET` was built from BSE's `ddlIndustry` master, which returns **IndustryNew**-level names ("Capital Goods", "Chemicals", "Automobile and Auto Components"), but is applied to the coarser **Sector** field, whose real values are "Consumer Discretionary", "Industrials", "Commodities", "Services", "Diversified". None of those five are in the table.
- The table can only emit 11 of the 18 valid sectors. Seven — `agriculture`, `construction_realestate`, `consumer_durables`, `defense`, `media_entertainment`, `railways_transport`, `textiles` — are unreachable.

Measured effect of keying on IndustryNew first, Sector as fallback: classified rises **1,698 → 3,747** of 4,684, with `other` falling from 2,986 to 937. Extending the table to the missing seven sectors recovers most of the remainder.

`sub_sector` derivation depends on `sector` being correct, so this cannot be deferred.

## File Structure

**Modify:** `app/companies/universe/sector_map.py`, `app/companies/universe/normalize.py`, `app/companies/universe/loader.py`, `app/models.py`, `app/db.py`, `app/scheduler.py`, `app/market/ripple.py`, `app/market/ripple_layers.py`, `app/routers/alerts.py`, `app/routers/stock_deep_dive.py`, `frontend/src/components/InsightCard.tsx`, `frontend/src/components/feed-v2/RippleSection.tsx`, `frontend/src/lib/api.ts`

**Create:** `app/companies/universe/sub_sector_map.py`, `backfill_reclassify.py`, plus tests per task.

---

# Phase 1 — Repair sector classification

### Task 1: Key sector_map on IndustryNew and cover all 18 sectors

**Files:**
- Modify: `app/companies/universe/sector_map.py`
- Test: `tests/test_universe_sector_map.py`

**Interfaces:**
- Produces: `map_sector(official_sector, official_industry=None) -> str` — signature gains an optional second argument; existing single-argument callers keep working.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_universe_sector_map.py`:

```python
import pytest

from app.analysis.schemas import SECTORS
from app.companies.universe import sector_map


@pytest.mark.parametrize("sector,industry,expected", [
    # The five Sector values that fall through today, each recovered via
    # IndustryNew. These five accounted for 2,971 production companies.
    ("Consumer Discretionary", "Automobile and Auto Components", "auto"),
    ("Consumer Discretionary", "Realty", "construction_realestate"),
    ("Consumer Discretionary", "Consumer Durables", "consumer_durables"),
    ("Consumer Discretionary", "Textiles", "textiles"),
    ("Industrials", "Capital Goods", "infra"),
    ("Industrials", "Construction", "infra"),
    ("Commodities", "Chemicals", "chemicals"),
    ("Commodities", "Metals & Mining", "metals"),
    ("Commodities", "Construction Materials", "infra"),
    ("Services", "Transport Services", "railways_transport"),
    # Sector still works when IndustryNew is absent or unknown.
    ("Energy", None, "oil_gas"),
    ("Financial Services", None, "banking"),
    ("Healthcare", "Something Unheard Of", "pharma"),
])
def test_industry_takes_precedence_then_sector_falls_back(sector, industry, expected):
    assert sector_map.map_sector(sector, industry) == expected


def test_previously_unreachable_sectors_are_now_reachable():
    # Seven of the 18 valid sectors could never be produced. A sector no
    # company can be assigned is a dead branch in fan-out and filtering.
    reachable = set(sector_map.OFFICIAL_SECTOR_TO_BUCKET.values())
    for missing in ("agriculture", "construction_realestate", "consumer_durables",
                    "defense", "media_entertainment", "railways_transport", "textiles"):
        assert missing in reachable


def test_every_emitted_value_is_a_valid_sector():
    assert set(sector_map.OFFICIAL_SECTOR_TO_BUCKET.values()) <= set(SECTORS)


def test_unknown_both_levels_is_other():
    assert sector_map.map_sector("Nonsense", "Also Nonsense") == "other"
    assert sector_map.map_sector(None, None) == "other"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_universe_sector_map.py -v`
Expected: FAIL — `map_sector() takes 1 positional argument but 2 were given`

- [ ] **Step 3: Rewrite the mapping and lookup**

In `app/companies/universe/sector_map.py`, replace `OFFICIAL_SECTOR_TO_BUCKET` and `map_sector`:

```python
# Keyed on BSE's IndustryNew level FIRST, with the coarser Sector level as a
# fallback. The original table was built from the ddlIndustry master, which
# returns IndustryNew names, but was applied to Sector -- so "Consumer
# Discretionary", "Industrials", "Commodities", "Services" and "Diversified"
# all fell through to "other", which was 2,971 production companies. Both
# levels live in one table because their vocabularies do not overlap except
# where they agree (e.g. "Energy").
OFFICIAL_SECTOR_TO_BUCKET = {
    # --- Sector level (coarse) ---
    "energy": "oil_gas",
    "financial services": "banking",
    "information technology": "it",
    "healthcare": "pharma",
    "fast moving consumer goods": "fmcg",
    "telecommunication": "telecom",
    "utilities": "infra",
    "diversified": "other",
    # --- IndustryNew level (finer; takes precedence) ---
    "oil, gas & consumable fuels": "oil_gas",
    "automobile and auto components": "auto",
    "capital goods": "infra",
    "construction": "infra",
    "construction materials": "infra",
    "power": "infra",
    "realty": "construction_realestate",
    "chemicals": "chemicals",
    "metals & mining": "metals",
    "consumer durables": "consumer_durables",
    "consumer services": "fmcg",
    "textiles": "textiles",
    "media, entertainment & publication": "media_entertainment",
    "media entertainment & publication": "media_entertainment",
    "transport services": "railways_transport",
    "transport infrastructure": "railways_transport",
    "agricultural food & other products": "agriculture",
    "fertilizers & agrochemicals": "agriculture",
    "forest materials": "other",
    "services": "other",
}


def map_sector(official_sector: str | None, official_industry: str | None = None) -> str:
    """BSE publishes four classification levels. IndustryNew is the finest one
    whose vocabulary matches this table, so it is tried first; Sector is the
    fallback for rows where IndustryNew is absent or unrecognised.

    Order matters and is the whole point of this function: keying on Sector
    alone left 65% of Indian companies as "other" in production.
    """
    for value in (official_industry, official_sector):
        if not value:
            continue
        bucket = OFFICIAL_SECTOR_TO_BUCKET.get(value.strip().lower())
        if bucket and bucket != "other":
            return bucket
    # Nothing matched to a real sector. Fall back to an explicit "other"
    # mapping if either level has one, else "other" by default -- same result,
    # but it distinguishes "we know this is other" from "we do not know".
    for value in (official_industry, official_sector):
        if value and OFFICIAL_SECTOR_TO_BUCKET.get(value.strip().lower()) == "other":
            return "other"
    return "other"
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_universe_sector_map.py -v`
Expected: all pass, including the pre-existing tests in that file.

- [ ] **Step 5: Update the caller**

In `app/companies/universe/normalize.py`, find the `build_records` line calling `sector_map.map_sector(record["official_sector"])` and change it to pass both levels:

```python
        record["sector"] = sector_map.map_sector(
            record["official_sector"], record["official_industry"],
        )
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: no new failures against the 1022 baseline. Tests asserting a specific sector for a fixture company may change — verify each change is a correction, not a regression, and say so in the report.

- [ ] **Step 7: Commit**

```bash
git add app/companies/universe/sector_map.py app/companies/universe/normalize.py tests/test_universe_sector_map.py
git commit -m "fix: key sector_map on IndustryNew, cover all 18 sectors

Keyed on Sector but built from ddlIndustry (IndustryNew names), so five
Sector values fell through to other -- 2,971 production companies. Seven of
18 valid sectors were also unreachable. Measured: classified 1,698 -> 3,747."
```

---

### Task 2: Re-derive sector for existing companies

**Files:**
- Create: `backfill_reclassify.py`
- Test: `tests/test_backfill_reclassify.py`

**Interfaces:**
- Produces: `reclassify(session, dry_run: bool = False) -> dict` returning `{"changed": int, "unchanged": int, "by_transition": dict}`.

Production already holds `official_sector` and `official_industry` for 4,669 companies. Re-deriving needs no fetch.

- [ ] **Step 1: Write the failing test**

Create `tests/test_backfill_reclassify.py`:

```python
import backfill_reclassify
from app.models import Company


def _co(session, ticker, sector, official_sector, official_industry):
    c = Company(ticker=ticker, name=ticker, sector=sector, index_tier="OTHER",
                official_sector=official_sector, official_industry=official_industry)
    session.add(c)
    session.commit()
    return c


def test_reclassifies_a_company_stuck_on_other(db_session):
    c = _co(db_session, "X.NS", "other", "Consumer Discretionary",
            "Automobile and Auto Components")
    result = backfill_reclassify.reclassify(db_session)
    assert db_session.get(Company, c.id).sector == "auto"
    assert result["changed"] == 1


def test_dry_run_changes_nothing(db_session):
    c = _co(db_session, "X.NS", "other", "Commodities", "Chemicals")
    result = backfill_reclassify.reclassify(db_session, dry_run=True)
    assert db_session.get(Company, c.id).sector == "other"
    assert result["changed"] == 1  # reported, not applied


def test_company_without_official_classification_is_untouched(db_session):
    c = _co(db_session, "X.NS", "banking", None, None)
    backfill_reclassify.reclassify(db_session)
    assert db_session.get(Company, c.id).sector == "banking"


def test_transitions_are_reported(db_session):
    _co(db_session, "A.NS", "other", "Industrials", "Capital Goods")
    _co(db_session, "B.NS", "other", "Industrials", "Capital Goods")
    result = backfill_reclassify.reclassify(db_session)
    assert result["by_transition"]["other -> infra"] == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_backfill_reclassify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backfill_reclassify'`

- [ ] **Step 3: Implement**

Create `backend/backfill_reclassify.py`:

```python
"""Re-derive Company.sector from the official classification already stored.

Needed because sector_map was keyed on BSE's Sector level while its table was
built from IndustryNew names, leaving 3,113 of 4,814 Indian companies as
"other" in production (2,971 of them despite having a valid classification).
Task 1 fixes the mapping; this applies it to rows already in the database.

No fetching: official_sector and official_industry are already stored.

    python backfill_reclassify.py --dry-run
    python backfill_reclassify.py
"""
import sys
from collections import Counter

from sqlalchemy.orm import Session

from app.companies.universe.sector_map import map_sector
from app.db import SessionLocal
from app.models import Company


def reclassify(session: Session, dry_run: bool = False) -> dict:
    """Recompute sector for every company that has an official classification.

    A company with no official_sector is left alone -- its sector came from
    somewhere else (the curated global seed, or the legacy keyword map) and
    this function has nothing better to offer.
    """
    changed = unchanged = 0
    transitions: Counter[str] = Counter()

    for company in session.query(Company).filter(Company.official_sector.isnot(None)).all():
        derived = map_sector(company.official_sector, company.official_industry)
        if derived == company.sector:
            unchanged += 1
            continue
        transitions[f"{company.sector} -> {derived}"] += 1
        changed += 1
        if not dry_run:
            company.sector = derived

    if dry_run:
        session.rollback()
    else:
        session.commit()
    return {"changed": changed, "unchanged": unchanged, "by_transition": dict(transitions)}


def main() -> None:
    dry = "--dry-run" in sys.argv
    session = SessionLocal()
    try:
        result = reclassify(session, dry_run=dry)
        print("DRY RUN -- nothing written" if dry else "APPLIED")
        print(f"  changed  : {result['changed']}")
        print(f"  unchanged: {result['unchanged']}")
        for transition, count in sorted(result["by_transition"].items(), key=lambda kv: -kv[1]):
            print(f"    {transition:44s} {count}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_backfill_reclassify.py -v`
Expected: 4 passed

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest -q` — no new failures.

```bash
git add backfill_reclassify.py tests/test_backfill_reclassify.py
git commit -m "feat: re-derive sector from stored official classification"
```

---

# Phase 2 — sub_sector from official ISubGroup

### Task 3: The ISubGroup mapping

**Files:**
- Create: `app/companies/universe/sub_sector_map.py`
- Test: `tests/test_universe_sub_sector_map.py`

**Interfaces:**
- Produces: `ISUBGROUP_TO_SUB_SECTOR: dict[str, str]`, `map_sub_sector(isubgroup: str | None, sector: str) -> str | None`.

190 distinct `ISubGroup` values appear in the 4,684 fetched detail files. The mapping targets the 72-value closed vocabulary in `app.companies.sub_sectors.SUB_SECTOR_TAXONOMY`. **Mapping on `ISubGroup` alone** — the sector is already derived, and `map_sub_sector` validates the pair rather than duplicating the sector in every key.

- [ ] **Step 1: Write the failing test**

Create `tests/test_universe_sub_sector_map.py`:

```python
from app.companies.sub_sectors import SUB_SECTOR_TAXONOMY
from app.companies.universe import sub_sector_map


def test_every_mapped_value_exists_in_the_closed_vocabulary():
    valid = {v for values in SUB_SECTOR_TAXONOMY.values() for v in values}
    unknown = set(sub_sector_map.ISUBGROUP_TO_SUB_SECTOR.values()) - valid
    assert unknown == set(), f"mappings target values outside the taxonomy: {unknown}"


def test_mapping_is_rejected_when_it_contradicts_the_sector():
    # "Private Sector Bank" belongs to banking. Asked for under sector "it",
    # the honest answer is None -- the sector is sourced and wins.
    assert sub_sector_map.map_sub_sector("Private Sector Bank", "banking") == "private_bank"
    assert sub_sector_map.map_sub_sector("Private Sector Bank", "it") is None


def test_unmapped_isubgroup_is_none_not_a_guess():
    assert sub_sector_map.map_sub_sector("Entirely Novel Business", "it") is None
    assert sub_sector_map.map_sub_sector(None, "it") is None
    assert sub_sector_map.map_sub_sector("", "it") is None


def test_lookup_is_case_and_whitespace_insensitive():
    assert sub_sector_map.map_sub_sector("  private sector bank  ", "banking") == "private_bank"


def test_known_high_volume_values_map(  ):
    # The five most common ISubGroup values in the real data, by company count.
    cases = [
        ("Non Banking Financial Company (NBFC)", "banking", "nbfc"),
        ("Pharmaceuticals", "pharma", "generics_formulations"),
        ("Auto Components & Equipments", "auto", "auto_component"),
        ("Specialty Chemicals", "chemicals", "specialty_chemicals"),
        ("Residential, Commercial Projects", "construction_realestate", "residential_developer"),
    ]
    for isub, sector, expected in cases:
        assert sub_sector_map.map_sub_sector(isub, sector) == expected
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_universe_sub_sector_map.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `app/companies/universe/sub_sector_map.py`. Keys are lowercased BSE `ISubGroup` values; values come from `SUB_SECTOR_TAXONOMY`. Unlisted values are deliberately absent — they resolve to `None`.

```python
"""BSE ISubGroup -> the app's closed sub-sector vocabulary.

190 distinct ISubGroup values appear across the 4,684 companies BSE classifies.
This maps the ones that correspond to a value in
app.companies.sub_sectors.SUB_SECTOR_TAXONOMY; anything absent resolves to None
rather than being forced into the nearest bucket.

Keyed on ISubGroup alone. The company's sector is derived separately from
official_sector/official_industry, and map_sub_sector VALIDATES the pair --
duplicating the sector into every key would let the two drift apart.

Pure data plus one function: no I/O, no DB, no app.models import.
"""
from app.companies.sub_sectors import SUB_SECTOR_TAXONOMY

ISUBGROUP_TO_SUB_SECTOR = {
    # --- oil_gas ---
    "oil exploration & production": "upstream_exploration",
    "refineries & marketing": "refining_marketing",
    "lpg/cng/png/lng supplier": "gas_distribution",
    "gas transmission/marketing": "gas_distribution",
    "trading - gas": "gas_distribution",
    "oil storage & transportation": "oil_gas_other",
    "oil equipment & services": "oil_gas_other",
    "offshore support solution drilling": "oil_gas_other",
    "lubricants": "oil_gas_other",
    # --- banking ---
    "private sector bank": "private_bank",
    "public sector bank": "psu_bank",
    "other bank": "banking_other",
    "non banking financial company (nbfc)": "nbfc",
    "microfinance institutions": "nbfc",
    "housing finance company": "housing_finance",
    "life insurance": "insurance",
    "general insurance": "insurance",
    "insurance distributors": "insurance",
    "asset management company": "asset_management",
    "investment company": "banking_other",
    "holding company": "banking_other",
    "other financial services": "banking_other",
    "stockbroking & allied": "banking_other",
    "financial institution": "banking_other",
    "financial technology (fintech)": "banking_other",
    "financial products distributor": "banking_other",
    "other capital market related services": "banking_other",
    "depositories, clearing houses and other intermediaries": "banking_other",
    "ratings": "banking_other",
    "exchange and data platform": "banking_other",
    # --- auto ---
    "passenger cars & utility vehicles": "passenger_vehicle",
    "2/3 wheelers": "two_wheeler",
    "cycles": "two_wheeler",
    "commercial vehicles": "commercial_vehicle",
    "construction vehicles": "commercial_vehicle",
    "tractors": "commercial_vehicle",
    "auto components & equipments": "auto_component",
    "tyres & rubber products": "auto_component",
    "trading - auto components": "auto_component",
    "auto -dealer": "auto_other",
    "dealers-commercial vehicles, tractors, construction vehicles": "auto_other",
    # --- it (see IT_SERVICES_ISUBGROUPS below for the cap-dependent cases) ---
    "software products": "product_saas",
    "computers hardware & equipments": "it_other",
    "data processing services": "it_other",
    # --- pharma ---
    "pharmaceuticals": "generics_formulations",
    "biotechnology": "specialty_pharma",
    "hospital": "hospital_diagnostics",
    "healthcare service provider": "hospital_diagnostics",
    "healthcare research, analytics & technology": "api_cdmo",
    "medical equipment & supplies": "pharma_other",
    "pharmacy retail": "pharma_other",
    "wellness": "pharma_other",
    # --- fmcg ---
    "packaged foods": "staples_food",
    "other food products": "staples_food",
    "edible oil": "staples_food",
    "sugar": "staples_food",
    "dairy products": "staples_food",
    "seafood": "staples_food",
    "meat products including poultry": "staples_food",
    "other agricultural products": "staples_food",
    "tea & coffee": "beverages",
    "breweries & distilleries": "beverages",
    "other beverages": "beverages",
    "personal care": "personal_care",
    "household products": "personal_care",
    "houseware": "personal_care",
    "diversified fmcg": "fmcg_other",
    "cigarettes & tobacco products": "fmcg_other",
    "animal feed": "fmcg_other",
    "speciality retail": "retail",
    "diversified retail": "retail",
    "e-retail/ e-commerce": "retail",
    "internet & catalogue retail": "retail",
    "distributors": "retail",
    # --- metals ---
    "iron & steel": "steel",
    "iron & steel products": "steel",
    "sponge iron": "steel",
    "pig iron": "steel",
    "ferro & silica manganese": "steel",
    "aluminium": "non_ferrous",
    "copper": "non_ferrous",
    "zinc": "non_ferrous",
    "aluminium, copper & zinc products": "non_ferrous",
    "precious metals": "non_ferrous",
    "diversified metals": "metals_other",
    "coal": "mining_coal",
    "trading coal": "mining_coal",
    "industrial minerals": "mining_coal",
    "trading - minerals": "metals_other",
    "trading - metals": "metals_other",
    # --- telecom ---
    "telecom - cellular & fixed line services": "telecom_operator",
    "telecom - infrastructure": "telecom_infrastructure",
    "telecom -  equipment & accessories": "telecom_infrastructure",
    "other telecom services": "telecom_other",
    # --- infra ---
    "civil construction": "construction_engineering",
    "road assets–toll, annuity, hybrid-annuity": "construction_engineering",
    "dredging": "construction_engineering",
    "power generation": "power_utilities",
    "integrated power utilities": "power_utilities",
    "power distribution": "power_utilities",
    "power trading": "power_utilities",
    "power - transmission": "power_utilities",
    "water supply & management": "power_utilities",
    "multi utilities": "power_utilities",
    "other utilities": "power_utilities",
    "heavy electrical equipment": "capital_goods",
    "other electrical equipment": "capital_goods",
    "industrial products": "capital_goods",
    "other industrial products": "capital_goods",
    "compressors, pumps & diesel engines": "capital_goods",
    "castings & forgings": "capital_goods",
    "abrasives & bearings": "capital_goods",
    "electrodes & refractories": "capital_goods",
    "cables - electricals": "capital_goods",
    "industrial gases": "capital_goods",
    "glass - industrial": "capital_goods",
    "cement & cement products": "cement",
    "other construction materials": "cement",
    "granites & marbles": "cement",
    "ceramics": "cement",
    "sanitary ware": "infra_other",
    "plywood boards/ laminates": "infra_other",
    "packaging": "infra_other",
    "plastic products - industrial": "infra_other",
    "waste management": "infra_other",
    # --- railways_transport ---
    "airline": "aviation",
    "airport & airport services": "aviation",
    "port & port services": "ports_shipping",
    "shipping": "ports_shipping",
    "logistics solution provider": "logistics_roadways",
    "road transport": "logistics_roadways",
    "transport related services": "logistics_roadways",
    "food storage facilities": "logistics_roadways",
    "railway wagons": "rail_equipment",
    # --- construction_realestate ---
    "residential, commercial projects": "residential_developer",
    "real estate related services": "construction_realestate_other",
    # --- defense ---
    "aerospace & defense": "defense_platforms",
    "ship building & allied services": "shipyard",
    "explosives": "defense_other",
    # --- agriculture ---
    "fertilizers": "fertilizers",
    "pesticides & agrochemicals": "agrochemicals",
    # --- consumer_durables ---
    "household appliances": "appliances_electronics",
    "consumer electronics": "appliances_electronics",
    "furniture, home furnishing": "appliances_electronics",
    "leisure products": "consumer_durables_other",
    "glass - consumer": "consumer_durables_other",
    "plastic products - consumer": "consumer_durables_other",
    "stationary": "consumer_durables_other",
    "diversified consumer products": "consumer_durables_other",
    # --- media_entertainment ---
    "tv broadcasting & software production": "broadcast_tv",
    "electronic media": "broadcast_tv",
    "film production, distribution & exhibition": "multiplex_film",
    "digital entertainment": "digital_gaming",
    "web based media and service": "digital_gaming",
    "print media": "media_entertainment_other",
    "printing & publication": "media_entertainment_other",
    "advertising & media agencies": "media_entertainment_other",
    "media & entertainment": "media_entertainment_other",
    # --- chemicals ---
    "specialty chemicals": "specialty_chemicals",
    "dyes and pigments": "specialty_chemicals",
    "printing inks": "specialty_chemicals",
    "commodity chemicals": "commodity_chemicals",
    "petrochemicals": "commodity_chemicals",
    "carbon black": "commodity_chemicals",
    "trading - chemicals": "commodity_chemicals",
    "paints": "paints",
    # --- textiles ---
    "garments & apparels": "apparel_garments",
    "footwear": "apparel_garments",
    "leather and leather products": "apparel_garments",
    "other textile products": "yarn_fabric",
    "trading - textile products": "yarn_fabric",
    "jute & jute products": "yarn_fabric",
    "rubber": "textiles_other",
}

# IT services cannot be split large-cap vs mid/small-cap from the industry
# taxonomy -- that distinction is about company size, which BSE does not
# encode. These resolve via the caller's cap tier; see map_sub_sector.
IT_SERVICES_ISUBGROUPS = {
    "computers - software & consulting",
    "it enabled services",
    "business process outsourcing (bpo)/ knowledge process outsourcing (kpo)",
}

_VALID = {sector: set(values) for sector, values in SUB_SECTOR_TAXONOMY.items()}


def map_sub_sector(isubgroup: str | None, sector: str, cap_tier: str | None = None) -> str | None:
    """Derive a sub_sector, or None.

    Returns None when the ISubGroup is unmapped, or when the mapped value does
    not belong to ``sector``'s list. The sector is itself sourced, so a
    contradiction means the mapping is wrong for this company -- reporting
    nothing beats reporting a sub_sector from a different industry.
    """
    if not isubgroup:
        return None
    key = isubgroup.strip().lower()

    if key in IT_SERVICES_ISUBGROUPS:
        # The vocabulary splits IT services by company SIZE, which BSE does
        # not encode. At ingest time cap tier is unknown -- it is a rank over
        # the whole population, computed later -- so asserting either bucket
        # would mislabel someone: "mid/small" is wrong for TCS, "large" is
        # wrong for the other ~240. it_other says what we actually know (it is
        # IT services) without claiming a size we cannot derive. A caller that
        # does know the tier gets the precise answer.
        if cap_tier == "LARGE":
            candidate = "it_services_large_cap"
        elif cap_tier in ("MID", "SMALL", "MICRO"):
            candidate = "it_services_mid_small_cap"
        else:
            candidate = "it_other"
    else:
        candidate = ISUBGROUP_TO_SUB_SECTOR.get(key)

    if candidate is None:
        return None
    return candidate if candidate in _VALID.get(sector, ()) else None
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_universe_sub_sector_map.py -v`
Expected: 5 passed. If `test_every_mapped_value_exists_in_the_closed_vocabulary` fails, a mapping targets a value not in the taxonomy — fix the mapping, never the taxonomy.

- [ ] **Step 5: Commit**

```bash
git add app/companies/universe/sub_sector_map.py tests/test_universe_sub_sector_map.py
git commit -m "feat: map BSE ISubGroup to the closed sub-sector vocabulary"
```

---

### Task 4: Derive sub_sector in the pipeline

**Files:**
- Modify: `app/companies/universe/normalize.py`, `app/companies/universe/loader.py`
- Test: `tests/test_universe_normalize.py`, `tests/test_universe_loader.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_universe_normalize.py`:

```python
def test_sub_sector_is_derived_from_isubgroup():
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    assert record["sub_sector"] == "refining_marketing"


def test_sub_sector_is_none_without_a_detail_payload():
    record = next(r for r in _load() if r["isin"] == "INE999Z01011")
    assert record["sub_sector"] is None
```

Append to `tests/test_universe_loader.py`:

```python
def test_sub_sector_is_written_with_the_classification(db_session):
    loader.upsert_records(db_session, [_record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited", sub_sector="refining_marketing")])
    assert db_session.query(Company).one().sub_sector == "refining_marketing"


def test_absent_sub_sector_never_clobbers_a_stored_one(db_session):
    loader.upsert_records(db_session, [_record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited", sub_sector="refining_marketing")])
    loader.upsert_records(db_session, [_record(
        "INE002A01018", "RELIANCE.NS", "Reliance Industries Limited",
        sub_sector=None, official_sector=None, classification_source=None,
    )])
    assert db_session.query(Company).one().sub_sector == "refining_marketing"


def test_unmapped_sub_sector_leaves_a_legacy_value_intact(db_session):
    # Spec 6.1: an unmapped ISubGroup must not null out one of the 824 legacy
    # LLM values. This differs from the test above -- here the classification
    # IS present and being written, only sub_sector is None.
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance", sector="oil_gas",
        index_tier="OTHER", isin="INE002A01018", sub_sector="legacy_value",
    ))
    db_session.commit()
    loader.upsert_records(db_session, [_record(
        "INE002A01018", "RELIANCE.NS", "Reliance Industries Limited", sub_sector=None,
    )])
    assert db_session.query(Company).one().sub_sector == "legacy_value"
```

Add `"sub_sector": None` to the `_record` helper's defaults in `tests/test_universe_loader.py`.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_universe_normalize.py tests/test_universe_loader.py -v`
Expected: FAIL — `KeyError: 'sub_sector'`

- [ ] **Step 3: Implement**

In `normalize.py`, add `"sub_sector": None` to `_blank_record`, import `sub_sector_map`, and in `build_records` — after `record["sector"]` is set — add:

```python
        record["sub_sector"] = sub_sector_map.map_sub_sector(
            record["official_isubgroup"], record["sector"],
        )
```

In `loader.py`, **do NOT add `sub_sector` to `_CLASSIFICATION_FIELDS`.** That group is written whenever `classification_source` is set, which would write `None` over an existing value whenever the ISubGroup is unmapped — contradicting spec §6.1, which says the 824 legacy values survive where no official mapping exists. Add a separate guard after the classification block instead:

```python
        # Spec 6.1: overwrite where we derived something, leave the legacy LLM
        # value alone where we did not. Folding this into
        # _CLASSIFICATION_FIELDS would null out 824 existing values the moment
        # their ISubGroup is unmapped.
        if record["sub_sector"] is not None:
            company.sub_sector = record["sub_sector"]
```

- [ ] **Step 4: Run tests, then the full suite**

Run: `python -m pytest tests/test_universe_normalize.py tests/test_universe_loader.py -v` then `python -m pytest -q`
Expected: all pass, no new failures.

- [ ] **Step 5: Commit**

```bash
git add app/companies/universe/normalize.py app/companies/universe/loader.py tests/test_universe_normalize.py tests/test_universe_loader.py
git commit -m "feat: derive sub_sector from official ISubGroup"
```

---

# Phase 3 — Financial ratios

### Task 5: Schema for the sixteen columns

**Files:**
- Modify: `app/models.py`, `app/db.py`
- Test: `tests/test_universe_schema.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_universe_schema.py`:

```python
def test_company_carries_financials_with_provenance(db_session):
    company = _company(
        eps=28.98, ceps=41.67, pe=44.95, pb=3.36, opm=14.24, npm=7.99, roe=7.48,
        con_eps=65.15, con_pe=19.99,
        financials_source="BSE", financials_as_of=date(2026, 8, 4),
    )
    db_session.add(company)
    db_session.commit()
    assert company.pe == 44.95
    assert company.con_pb is None          # BSE genuinely returns None here
    assert company.financials_source == "BSE"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_universe_schema.py -v`
Expected: FAIL — `TypeError: 'eps' is an invalid keyword argument for Company`

- [ ] **Step 3: Add the columns**

In `app/models.py`, after the universe/provenance block in `class Company`:

```python
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
```

Append to `_ADDED_COLUMNS` in `app/db.py`:

```python
    ("companies", "eps", "FLOAT"),
    ("companies", "ceps", "FLOAT"),
    ("companies", "pe", "FLOAT"),
    ("companies", "pb", "FLOAT"),
    ("companies", "opm", "FLOAT"),
    ("companies", "npm", "FLOAT"),
    ("companies", "roe", "FLOAT"),
    ("companies", "con_eps", "FLOAT"),
    ("companies", "con_ceps", "FLOAT"),
    ("companies", "con_pe", "FLOAT"),
    ("companies", "con_pb", "FLOAT"),
    ("companies", "con_opm", "FLOAT"),
    ("companies", "con_npm", "FLOAT"),
    ("companies", "con_roe", "FLOAT"),
    ("companies", "financials_source", "VARCHAR"),
    ("companies", "financials_as_of", "DATE"),
```

- [ ] **Step 4: Run tests and verify the migration**

Run: `python -m pytest tests/test_universe_schema.py -v` then `python -m pytest -q`

Then: `python -c "from app.db import init_db; init_db(); print('ok')"` and confirm the columns exist via `PRAGMA table_info(companies)`.

- [ ] **Step 5: Commit**

```bash
git add app/models.py app/db.py tests/test_universe_schema.py
git commit -m "feat: add BSE fundamentals columns with provenance"
```

---

### Task 6: Extract and persist the ratios

**Files:**
- Modify: `app/companies/universe/normalize.py`, `app/companies/universe/loader.py`
- Test: `tests/test_universe_normalize.py`, `tests/test_universe_loader.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_universe_normalize.py`:

```python
def test_ratios_are_extracted_from_the_detail_payload():
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    assert record["eps"] == 28.98
    assert record["opm"] == 14.24
    assert record["financials_source"] == "BSE"
    assert record["financials_as_of"] == AS_OF


def test_absent_ratio_is_none_never_zero():
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    # The real BSE payload returns None for ConPB. Zero would render as a
    # real price-to-book of 0.00.
    assert record["con_pb"] is None


def test_no_detail_payload_means_no_ratios_and_no_provenance():
    record = next(r for r in _load() if r["isin"] == "INE999Z01011")
    assert record["eps"] is None
    assert record["financials_source"] is None
```

Update the fixture `tests/fixtures/universe/2026-08-03/bse_detail/500325.json` to include the ratio fields (matching the real payload):

```json
{"SecurityId": "RELIANCE", "SecurityCode": "500325", "ISIN": "INE002A01018",
 "Industry": "Refineries & Marketing", "Group": "A", "Sector": "Energy",
 "IndustryNew": "Oil, Gas & Consumable Fuels", "IGroup": "Petroleum Products",
 "ISubGroup": "Refineries & Marketing",
 "EPS": "28.98", "CEPS": "41.67", "PE": "44.95", "PB": "3.36",
 "OPM": "14.24", "NPM": "7.99", "ROE": "7.48",
 "ConEPS": "65.15", "ConCEPS": "108.71", "ConPE": "19.99",
 "ConOPM": "0.00", "ConNPM": "0.00", "ConPB": null, "ConROE": null}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_universe_normalize.py -v`
Expected: FAIL — `KeyError: 'eps'`

- [ ] **Step 3: Implement**

In `normalize.py`, add a module constant and extend the detail branch of `build_records`:

```python
# (record key, BSE payload key). Standalone first, consolidated second.
_RATIO_FIELDS = (
    ("eps", "EPS"), ("ceps", "CEPS"), ("pe", "PE"), ("pb", "PB"),
    ("opm", "OPM"), ("npm", "NPM"), ("roe", "ROE"),
    ("con_eps", "ConEPS"), ("con_ceps", "ConCEPS"), ("con_pe", "ConPE"),
    ("con_pb", "ConPB"), ("con_opm", "ConOPM"), ("con_npm", "ConNPM"),
    ("con_roe", "ConROE"),
)
```

Add every ratio key plus `financials_source`/`financials_as_of` to `_blank_record` with `None`. Then inside `if detail:` in `build_records`:

```python
            got_any_ratio = False
            for key, source_key in _RATIO_FIELDS:
                value = _parse_float(detail.get(source_key))
                record[key] = value
                if value is not None:
                    got_any_ratio = True
            if got_any_ratio:
                record["financials_source"] = "BSE"
                record["financials_as_of"] = as_of
```

Note `_parse_float` already rejects non-finite values and strips commas — reuse it rather than adding a second parser.

In `loader.py`, add a third field group beside `_ALWAYS_FIELDS` and `_CLASSIFICATION_FIELDS`:

```python
# Written only when the payload actually carried ratios, so the daily master
# refresh (which runs with an empty bse_detail/) cannot blank them.
_FINANCIAL_FIELDS = (
    "eps", "ceps", "pe", "pb", "opm", "npm", "roe",
    "con_eps", "con_ceps", "con_pe", "con_pb", "con_opm", "con_npm", "con_roe",
    "financials_source", "financials_as_of",
)
```

and in `upsert_records`, after the classification block:

```python
        if record["financials_source"]:
            for field in _FINANCIAL_FIELDS:
                setattr(company, field, record[field])
```

- [ ] **Step 4: Run tests and the full suite**

Run: `python -m pytest tests/test_universe_normalize.py tests/test_universe_loader.py -v` then `python -m pytest -q`

- [ ] **Step 5: Commit**

```bash
git add app/companies/universe/normalize.py app/companies/universe/loader.py tests/ 
git commit -m "feat: persist BSE fundamentals from the detail payload"
```

---

# Phase 4 — Surface and retirement

### Task 7: The fundamentals API object

**Files:**
- Create: `app/companies/fundamentals.py`
- Modify: `app/market/ripple.py`, `app/market/ripple_layers.py`, `app/routers/alerts.py`, `app/routers/stock_deep_dive.py`
- Test: `tests/test_fundamentals.py`

**Interfaces:**
- Produces: `fundamentals_payload(company) -> dict | None`.

One helper, four call sites — the shape must not drift between them.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fundamentals.py`:

```python
from datetime import date

from app.companies.fundamentals import fundamentals_payload
from app.models import Company


def _co(**kw):
    base = dict(ticker="X.NS", name="X", sector="oil_gas", index_tier="OTHER")
    base.update(kw)
    return Company(**base)


def test_full_payload():
    p = fundamentals_payload(_co(
        official_sector="Energy", official_industry="Oil, Gas & Consumable Fuels",
        official_igroup="Petroleum Products", official_isubgroup="Refineries & Marketing",
        eps=28.98, pe=44.95, financials_source="BSE", financials_as_of=date(2026, 8, 4),
    ))
    assert p["classification"]["sub_group"] == "Refineries & Marketing"
    assert p["ratios"]["eps"] == 28.98
    assert p["as_of"] == "2026-08-04"


def test_null_ratios_are_omitted_not_zeroed():
    p = fundamentals_payload(_co(
        official_sector="Energy", eps=28.98, roe=None,
        financials_source="BSE", financials_as_of=date(2026, 8, 4),
    ))
    assert "roe" not in p["ratios"]
    assert p["ratios"]["eps"] == 28.98


def test_classification_without_ratios_omits_the_ratios_key():
    p = fundamentals_payload(_co(official_sector="Energy"))
    assert p["classification"]["sector"] == "Energy"
    assert "ratios" not in p
    assert "consolidated" not in p


def test_no_classification_yields_none():
    assert fundamentals_payload(_co()) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_fundamentals.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `app/companies/fundamentals.py`:

```python
"""One shape for the company-fundamentals payload, used by all four
serializers so it cannot drift between them.

Replaces the LLM-written business_desc: what a company does is expressed as
BSE's official classification plus the ratios BSE publishes, each traceable to
a source and an as-of date. See docs/superpowers/specs/2026-08-04-sourced-
company-fundamentals-design.md.
"""
from app.models import Company

_RATIOS = ("eps", "ceps", "pe", "pb", "opm", "npm", "roe")
_CONSOLIDATED = (
    ("eps", "con_eps"), ("ceps", "con_ceps"), ("pe", "con_pe"), ("pb", "con_pb"),
    ("opm", "con_opm"), ("npm", "con_npm"), ("roe", "con_roe"),
)


def fundamentals_payload(company: Company) -> dict | None:
    """None when the company has no official classification (the curated
    global rows and NSE-only names). A NULL ratio is OMITTED rather than sent
    as 0 -- a client must not be able to read absent data as a real zero, and
    an empty ratios object invites exactly that.
    """
    if not company.official_sector:
        return None

    payload: dict = {
        "classification": {
            "sector": company.official_sector,
            "industry": company.official_industry,
            "group": company.official_igroup,
            "sub_group": company.official_isubgroup,
        },
        "source": company.classification_source,
        "as_of": company.classification_as_of.isoformat() if company.classification_as_of else None,
    }

    ratios = {k: getattr(company, k) for k in _RATIOS if getattr(company, k) is not None}
    consolidated = {k: getattr(company, a) for k, a in _CONSOLIDATED if getattr(company, a) is not None}
    if ratios:
        payload["ratios"] = ratios
    if consolidated:
        payload["consolidated"] = consolidated
    if company.financials_source:
        payload["source"] = company.financials_source
        if company.financials_as_of:
            payload["as_of"] = company.financials_as_of.isoformat()
    return payload
```

- [ ] **Step 4: Wire the four serializers**

In each of `app/market/ripple.py` (line ~65), `app/market/ripple_layers.py` (~139), `app/routers/alerts.py` (~188) and `app/routers/stock_deep_dive.py` (~38), keep the `business_desc` key but make it always `None`, and add `fundamentals` beside it:

```python
            # business_desc was LLM-invented and is no longer populated; the
            # key stays so the frontend can migrate without a lockstep deploy.
            "business_desc": None,
            "fundamentals": fundamentals_payload(company),
```

Use whichever local variable holds the company at each site (`company`, or `ac.company` in `alerts.py`).

- [ ] **Step 5: Run tests and the full suite**

Run: `python -m pytest tests/test_fundamentals.py -v` then `python -m pytest -q`
Expected: tests asserting a non-null `business_desc` in API responses will fail — update them to assert `None` plus a populated `fundamentals`. Do not restore the old behaviour.

- [ ] **Step 6: Commit**

```bash
git add app/companies/fundamentals.py app/market/ripple.py app/market/ripple_layers.py app/routers/alerts.py app/routers/stock_deep_dive.py tests/
git commit -m "feat: serve sourced fundamentals, stop serving invented business_desc"
```

---

### Task 8: Retire the LLM description path

**Files:**
- Modify: `app/scheduler.py`
- Test: `tests/test_scheduler_universe.py`

**This is the most urgent task in the plan.** `_run_business_profile_refresh` selects every company with a NULL `business_desc` and asks an LLM to invent one, every 6 hours. Subsystem A took that population from ~840 to ~5,140.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scheduler_universe.py`:

```python
def test_business_profile_refresh_is_no_longer_scheduled():
    # It fabricated a business description for every company with a NULL one,
    # every 6 hours. After the universe ingest that is ~5,140 companies.
    import app.scheduler as scheduler
    assert not hasattr(scheduler, "_run_business_profile_refresh")


def test_registered_job_ids_do_not_include_the_profile_refresh():
    # Assert on the scheduler's own registry, not on source text -- a prior
    # review found a getsource-based assertion hid a real defect for 20 tasks.
    import app.scheduler as scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    sched = BackgroundScheduler()
    scheduler.scheduler = sched
    scheduler.start_scheduler()
    try:
        assert "business_profile_refresh" not in {j.id for j in sched.get_jobs()}
    finally:
        sched.shutdown(wait=False)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_scheduler_universe.py -v`
Expected: FAIL — the attribute and the job id both still exist.

- [ ] **Step 3: Remove the job**

In `app/scheduler.py`, delete the `_run_business_profile_refresh` function (~lines 248-262) and its `scheduler.add_job(...)` registration with `id="business_profile_refresh"`. Remove any import left unused by the deletion (`generate_business_profiles_batch`, and `json` if nothing else uses it).

Leave `app/companies/business_profile.py` and `backfill_business_profiles.py` on disk, unreferenced — the work is recoverable and nothing runs it.

- [ ] **Step 4: Run tests and the full suite**

Run: `python -m pytest tests/test_scheduler_universe.py -v` then `python -m pytest -q`
Expected: `tests/test_business_profile.py` still passes — it tests the module directly, which still exists.

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py tests/test_scheduler_universe.py
git commit -m "fix: stop the scheduler fabricating business descriptions

The job asked an LLM to invent a description for every company with a NULL
business_desc, every 6 hours. The universe ingest took that population from
~840 to ~5,140."
```

---

### Task 9: Frontend

**Files:**
- Modify: `frontend/src/lib/api.ts`, `frontend/src/components/InsightCard.tsx`, `frontend/src/components/feed-v2/RippleSection.tsx`
- Test: `frontend/src/components/InsightCard.test.tsx`, `frontend/src/components/feed-v2/RippleSection.test.tsx`

- [ ] **Step 1: Add the type**

In `frontend/src/lib/api.ts`, add beside the existing company types:

```ts
export interface Fundamentals {
  classification: {
    sector: string | null;
    industry: string | null;
    group: string | null;
    sub_group: string | null;
  };
  ratios?: Partial<Record<"eps" | "ceps" | "pe" | "pb" | "opm" | "npm" | "roe", number>>;
  consolidated?: Partial<Record<"eps" | "ceps" | "pe" | "pb" | "opm" | "npm" | "roe", number>>;
  source: string | null;
  as_of: string | null;
}
```

and add `fundamentals?: Fundamentals | null` wherever `business_desc` appears on a company-bearing interface.

- [ ] **Step 2: Write the failing test**

In `InsightCard.test.tsx`, replace any assertion on `business_desc` text with:

```tsx
it("renders the sourced classification and ratios with an as-of date", () => {
  render(<InsightCard {...propsWith({
    business_desc: null,
    fundamentals: {
      classification: { sector: "Energy", industry: "Oil, Gas & Consumable Fuels",
                        group: "Petroleum Products", sub_group: "Refineries & Marketing" },
      ratios: { pe: 44.95, opm: 14.24 },
      source: "BSE", as_of: "2026-08-04",
    },
  })} />);
  expect(screen.getByText(/Refineries & Marketing/)).toBeInTheDocument();
  expect(screen.getByText(/44.95/)).toBeInTheDocument();
  // The date is load-bearing, not decoration: PE is price-derived and this
  // data refreshes monthly (spec 5.1).
  expect(screen.getByText(/2026-08-04/)).toBeInTheDocument();
});

it("renders nothing when fundamentals is null", () => {
  const { container } = render(<InsightCard {...propsWith({ business_desc: null, fundamentals: null })} />);
  expect(container.querySelector("[data-testid='fundamentals']")).toBeNull();
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npm test -- InsightCard`
Expected: FAIL — nothing renders `fundamentals`.

- [ ] **Step 4: Implement**

Add a shared presentational component, `frontend/src/components/Fundamentals.tsx`, and use it at both call sites so the two panels cannot drift:

```tsx
import type { Fundamentals as FundamentalsData } from "../lib/api";

const RATIO_LABELS: Array<[keyof NonNullable<FundamentalsData["ratios"]>, string]> = [
  ["pe", "P/E"], ["pb", "P/B"], ["eps", "EPS"],
  ["opm", "OPM %"], ["npm", "NPM %"], ["roe", "ROE %"],
];

export function Fundamentals({ data }: { data: FundamentalsData | null | undefined }) {
  if (!data) return null;                      // no invented filler
  const { classification: c, ratios, as_of, source } = data;
  const path = [c.sector, c.industry, c.group, c.sub_group].filter(Boolean);
  const shown = RATIO_LABELS.filter(([k]) => ratios?.[k] !== undefined);

  return (
    <div data-testid="fundamentals" className="fundamentals">
      {path.length > 0 && <div className="fundamentals__path">{path.join(" › ")}</div>}
      {shown.length > 0 && (
        <dl className="fundamentals__ratios">
          {shown.map(([k, label]) => (
            <div key={k}>
              <dt>{label}</dt>
              <dd>{ratios![k]!.toFixed(2)}</dd>
            </div>
          ))}
        </dl>
      )}
      {/* The date is load-bearing, not a caption: P/E and P/B are
          price-derived and this data refreshes monthly (spec 5.1). */}
      {as_of && (
        <div className="fundamentals__source">
          {source ?? "source unknown"} · as of {as_of}
        </div>
      )}
    </div>
  );
}
```

Then in `InsightCard.tsx` and `RippleSection.tsx`, delete the `business_desc` paragraph and render `<Fundamentals data={company.fundamentals} />` in its place. Style `.fundamentals` to match the existing editorial treatment — serif/mono, hairline rules, no emoji.

- [ ] **Step 5: Run the frontend tests**

Run: `cd frontend && npm test`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat: render sourced fundamentals instead of invented prose"
```

---

## Rollout

After all tasks pass, in order:

```bash
# 1. Deploy (Railway auto-deploys master)
git push origin HEAD:master

# 2. Once the deploy is healthy, re-derive sector on the live data
railway ssh --service newsflo-app -- "cd /app && python backfill_reclassify.py --dry-run"
railway ssh --service newsflo-app -- "cd /app && python backfill_reclassify.py"

# 3. Re-run the ingest load to populate sub_sector and the ratios from the
#    detail files already on disk (no refetch)
railway ssh --service newsflo-app -- "cd /app && python -c \"
from datetime import date
from app.db import SessionLocal
import ingest_universe
s = SessionLocal()
print(ingest_universe.run_ingest('data/universe', date.today(), s, fetch=False))
s.close()\""

# 4. Verify
railway ssh --service newsflo-app -- "cd /app && python -c \"
import os, psycopg2
c=psycopg2.connect(os.environ['DATABASE_URL']); cur=c.cursor()
for label, sql in [
  ('sector=other', \\\"select count(*) from companies where market='INDIA' and sector='other'\\\"),
  ('with sub_sector', 'select count(*) from companies where sub_sector is not null'),
  ('with eps', 'select count(*) from companies where eps is not null'),
]:
    cur.execute(sql); print(label, cur.fetchone()[0])\""
```

Expected after step 4: `sector=other` falls from 3,113 to roughly 900; `with sub_sector` rises from 824 to several thousand; `with eps` lands near 4,600.

**Take a backup first** — the `backup_20260804` schema from the previous migration is still present and can be refreshed with the same `CREATE TABLE backup_x AS SELECT * FROM public.x` approach.

**Rollback:** step 2 only rewrites `sector`, which is derivable, so re-running the previous mapping restores it. Steps 3 only adds.
