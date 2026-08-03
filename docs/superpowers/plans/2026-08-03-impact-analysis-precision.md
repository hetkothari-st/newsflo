# Impact Analysis Precision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the affected-companies list from showing companies with no genuine connection to the news (the "Eternal Ltd. on a crude-oil story" bug), and raise coverage on the 61% of alerts that currently show no companies at all.

**Architecture:** The bug is architectural, not prompt quality. `app/analysis/cascade.py::_sector_fanout_mentions` synthesizes one sector-wide mention per sector per cascade level, which `app/companies/resolution.py::resolve_companies` expands into the top-5 index-tier constituents with a template rationale. Those rows carry `impact_level="direct"`, so `app/market/ripple_layers.py` routes them into the DIRECT bucket. The fix keeps a quarantined sector-exposure tier (reusing the existing `SECTOR_WIDE` bucket), grounds company selection in real DB rows instead of model recall, and adds an explicit per-company verification pass.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, Pydantic v2, pytest, SQLite (dev/test) + Postgres (prod), Gemini (primary) + Groq (fallback) via OpenAI-shape adapters.

**Spec:** `docs/superpowers/specs/2026-08-03-impact-analysis-precision-design.md`

## Global Constraints

- **No frontend layout, section, or category changes.** No category may be added, removed, or renamed. The three-tier card-back sectioning (LLM-adaptive → static archetype template → per-sector split) keeps all three tiers. All seven `_LAYER_ORDER` relationships keep their existing order. `impact_level` keeps exactly `direct` / `indirect_l1` / `indirect_l2`.
- **Backend, plus three null-safety lines in the frontend.** `AlertCompany.rationale` becomes nullable in Task 6, so `frontend/src/lib/api.ts` and two components that read it need null guards. That is the *only* frontend change in this plan, it changes no rendered output for a row that has a rationale, and it is not licence to touch anything else in the frontend.
- Run backend commands from `backend/`. Test command is `python -m pytest`. Frontend checks run from `frontend/` via `npm run typecheck && npm test`.
- **Omit rather than mismatch.** When a value cannot be resolved confidently, drop the row rather than guess — the established discipline in `app/companies/resolution.py`.
- **Never fabricate a number.** All LLM-generated text passes `app/reasoning/compliance.py::validate_no_advice_language` before persistence.
- **Degrade, never crash.** Any new LLM call must return a safe empty value on failure rather than propagating, matching `app/analysis/refinement.py`.
- Provider enum constraints are **not** reliably enforced for nested array items (documented at `app/analysis/cascade.py:282`). Every enum-constrained field needs a defensive post-filter in Python.
- Existing tests must keep passing. Full suite before every commit.

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `backend/app/companies/candidates.py` | Query + format the real-company candidate list injected into analysis prompts |
| `backend/app/analysis/verification.py` | The per-company "does this belong?" LLM pass |
| `backend/app/companies/integrity.py` | Deterministic sector/sub_sector taxonomy validation |
| `backend/tests/test_candidates.py` | Tests for candidate retrieval |
| `backend/tests/test_verification.py` | Tests for the verification pass |
| `backend/tests/test_integrity.py` | Tests for taxonomy validation |
| `backend/tests/golden/__init__.py` | Golden-set package marker |
| `backend/tests/golden/cases.py` | Hand-labelled golden alerts (must-include / must-exclude) |
| `backend/tests/golden/score.py` | Precision/recall scorer |
| `backend/tests/test_golden_scorer.py` | Tests for the scorer itself |
| `backend/migrate_precision.py` | One-off SQL migration over existing alerts |
| `backend/audit_taxonomy.py` | Prints NIFTY50 sector/sub_sector rows for human review |

**Modified files:**

| Path | Change |
|---|---|
| `backend/app/market/ripple_layers.py` | Bucket dispatch on `basis`; exclude fan-out from tier-1 claiming |
| `backend/app/analysis/refinement.py` | Offer only `direct_mention` rows to `generate_ripple_layers`; log tier-1 failure |
| `backend/app/companies/resolution.py` | `rationale=None` for fan-out rows; sub-sector anchored selection; `TOP_N` 5→3 |
| `backend/app/pipeline.py` | Confidence floor; direction/rationale coherence |
| `backend/app/analysis/cascade.py` | Candidate grounding; verification wiring; fan-out gating |
| `backend/app/analysis/claude_client.py` | `GeminiAdapter` honors `model`; `temperature` |
| `backend/app/models.py` | `AlertCompany.rationale` becomes nullable |
| `frontend/src/lib/api.ts` | `rationale` typed `string \| null` |
| `frontend/src/components/InsightCard.tsx` | Null guard on `rationale` |
| `frontend/src/components/ReasoningPanel.tsx` | Null guard on `rationale` |

---

## Task 1: Golden-set harness

Builds the ruler. Every later task is scored against it. Nothing here calls an LLM — cases are captured from the existing database, and the scorer compares a set of tickers against expectations.

**Files:**
- Create: `backend/tests/golden/__init__.py`
- Create: `backend/tests/golden/cases.py`
- Create: `backend/tests/golden/score.py`
- Create: `backend/tests/test_golden_scorer.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `GoldenCase` — dataclass with fields `alert_id: int`, `title: str`, `must_include: set[str]`, `must_exclude: set[str]`.
  - `GOLDEN_CASES: list[GoldenCase]`
  - `score_case(case: GoldenCase, actual_tickers: set[str]) -> CaseScore`
  - `CaseScore` — dataclass with `alert_id: int`, `missing: set[str]`, `forbidden: set[str]`, `precision: float`, `recall: float`
  - `score_all(results: dict[int, set[str]]) -> RunScore`
  - `RunScore` — dataclass with `cases: list[CaseScore]`, `mean_precision: float`, `mean_recall: float`, `total_forbidden: int`

- [ ] **Step 1: Create the package marker**

```python
# backend/tests/golden/__init__.py
"""Golden-set fixtures and scorer for impact-analysis precision.

Hand-labelled alerts with the companies that MUST appear and the companies
that MUST NOT. See docs/superpowers/specs/2026-08-03-impact-analysis-
precision-design.md Section 0 -- this is the ruler every other section is
measured against.
"""
```

- [ ] **Step 2: Write the failing scorer test**

```python
# backend/tests/test_golden_scorer.py
from tests.golden.cases import GoldenCase
from tests.golden.score import score_all, score_case


def _case(**overrides):
    defaults = {
        "alert_id": 1,
        "title": "test",
        "must_include": {"A.NS"},
        "must_exclude": {"BAD.NS"},
    }
    defaults.update(overrides)
    return GoldenCase(**defaults)


def test_perfect_result_scores_1_0():
    result = score_case(_case(), {"A.NS"})
    assert result.missing == set()
    assert result.forbidden == set()
    assert result.precision == 1.0
    assert result.recall == 1.0


def test_forbidden_ticker_is_reported():
    result = score_case(_case(), {"A.NS", "BAD.NS"})
    assert result.forbidden == {"BAD.NS"}
    assert result.recall == 1.0
    assert result.precision == 0.5


def test_missing_ticker_lowers_recall():
    result = score_case(_case(must_include={"A.NS", "B.NS"}), {"A.NS"})
    assert result.missing == {"B.NS"}
    assert result.recall == 0.5


def test_unlabelled_extra_ticker_is_not_forbidden():
    # A company that is neither required nor banned is not scored against --
    # the label set is deliberately partial, so an unlabelled name is
    # "unknown", not "wrong".
    result = score_case(_case(), {"A.NS", "UNLABELLED.NS"})
    assert result.forbidden == set()
    assert result.precision == 1.0


def test_empty_result_scores_zero_recall_not_a_crash():
    result = score_case(_case(), set())
    assert result.missing == {"A.NS"}
    assert result.recall == 0.0
    assert result.precision == 1.0


def test_score_all_aggregates_and_counts_forbidden():
    cases = [_case(alert_id=1), _case(alert_id=2)]
    run = score_all({1: {"A.NS"}, 2: {"A.NS", "BAD.NS"}}, cases=cases)
    assert run.total_forbidden == 1
    assert run.mean_recall == 1.0
    assert run.mean_precision == 0.75


def test_score_all_treats_a_missing_alert_as_empty():
    cases = [_case(alert_id=1), _case(alert_id=2)]
    run = score_all({1: {"A.NS"}}, cases=cases)
    assert run.mean_recall == 0.5
```

- [ ] **Step 3: Run it to make sure it fails**

Run: `python -m pytest tests/test_golden_scorer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.golden.cases'`

- [ ] **Step 4: Implement the case dataclass and an initial seeded case**

```python
# backend/tests/golden/cases.py
"""Hand-labelled golden alerts.

`must_include` / `must_exclude` are deliberately PARTIAL: they name only the
companies a human is confident about. A ticker in neither set is treated as
unknown and does not count for or against a run -- so adding a case is cheap
and never punishes the pipeline for a judgement call nobody made.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GoldenCase:
    alert_id: int
    title: str
    must_include: set[str] = field(default_factory=set)
    must_exclude: set[str] = field(default_factory=set)


GOLDEN_CASES: list[GoldenCase] = [
    GoldenCase(
        alert_id=9020,
        title="Crude oil supply shock hits refiners",
        must_include={"HPCL.NS", "BPCL.NS", "INDIGO.NS", "ASIANPAINT.NS"},
        must_exclude={
            # Food delivery / quick commerce -- no crude mechanism. The
            # original reported bug.
            "ETERNAL.NS",
            # Reached only via the L1/L2 fan-out, which had no article-
            # specific mechanism for any of them.
            "BAJAJ-AUTO.NS", "MARUTI.NS", "EICHERMOT.NS", "M&M.NS", "TMPV.NS",
            "HDFCBANK.NS", "AXISBANK.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS",
            "HDFCLIFE.NS", "NTPC.NS", "POWERGRID.NS", "ULTRACEMCO.NS",
            # Demo seed row that should not exist in production at all.
            "SOMETEXTILE.NS",
        },
    ),
]
```

- [ ] **Step 5: Implement the scorer**

```python
# backend/tests/golden/score.py
"""Scores a pipeline run against the golden set.

precision here is deliberately NOT the textbook definition: it is measured
only over LABELLED tickers (must_include + must_exclude), because the label
sets are partial. An unlabelled ticker is ignored entirely.
"""
from dataclasses import dataclass

from tests.golden.cases import GOLDEN_CASES, GoldenCase


@dataclass(frozen=True)
class CaseScore:
    alert_id: int
    missing: set[str]
    forbidden: set[str]
    precision: float
    recall: float


@dataclass(frozen=True)
class RunScore:
    cases: list[CaseScore]
    mean_precision: float
    mean_recall: float
    total_forbidden: int


def score_case(case: GoldenCase, actual_tickers: set[str]) -> CaseScore:
    missing = case.must_include - actual_tickers
    forbidden = case.must_exclude & actual_tickers

    hits = len(case.must_include & actual_tickers)
    # Denominator is labelled tickers the run actually returned, so an
    # unlabelled extra never costs precision.
    labelled_returned = hits + len(forbidden)
    precision = 1.0 if labelled_returned == 0 else hits / labelled_returned
    recall = 1.0 if not case.must_include else hits / len(case.must_include)

    return CaseScore(
        alert_id=case.alert_id, missing=missing, forbidden=forbidden,
        precision=precision, recall=recall,
    )


def score_all(results: dict[int, set[str]], cases: list[GoldenCase] | None = None) -> RunScore:
    """results: {alert_id: set of tickers the pipeline produced}. An alert_id
    absent from `results` is scored as an empty result rather than skipped --
    a case the pipeline dropped entirely is a failure, not a non-event."""
    cases = GOLDEN_CASES if cases is None else cases
    scored = [score_case(c, results.get(c.alert_id, set())) for c in cases]
    n = len(scored) or 1
    return RunScore(
        cases=scored,
        mean_precision=sum(s.precision for s in scored) / n,
        mean_recall=sum(s.recall for s in scored) / n,
        total_forbidden=sum(len(s.forbidden) for s in scored),
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_golden_scorer.py -v`
Expected: PASS — 7 passed

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest`
Expected: PASS — no previously-passing test broken

- [ ] **Step 8: Commit**

```bash
git add backend/tests/golden backend/tests/test_golden_scorer.py
git commit -m "test: golden-set harness for impact-analysis precision

Partial label sets (must_include / must_exclude) so an unlabelled ticker is
scored as unknown rather than wrong, making cases cheap to add. Seeds the
reported alert-9020 case: Eternal Ltd. and the whole L1/L2 fan-out are
must_exclude, the refiners and crude-exposed names are must_include."
```

> **Note for the human:** `GOLDEN_CASES` has one case. Before Task 10 lands, add ~29 more by picking alerts from the existing DB and labelling them. Everything works with one case; the numbers just get more meaningful with thirty.

---

## Task 2: Purge demo seed data from `companies`

Spec Section 9. Small and independent — `SOMETEXTILE.NS` ("Demo Textiles Ltd") is a live, resolvable row that the sector fan-out injected into real alerts.

**Files:**
- Create: `backend/app/companies/integrity.py`
- Create: `backend/tests/test_integrity.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DEMO_TICKERS: frozenset[str]`
  - `is_demo_company(ticker: str) -> bool`
  - `delete_demo_companies(session) -> list[str]` — returns deleted tickers

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_integrity.py
from app.companies.integrity import (
    delete_demo_companies, is_demo_company,
)
from app.models import Company


def test_known_demo_ticker_is_flagged():
    assert is_demo_company("SOMETEXTILE.NS") is True


def test_real_ticker_is_not_flagged():
    assert is_demo_company("RELIANCE.NS") is False


def test_delete_demo_companies_removes_only_demo_rows(db_session):
    db_session.add(Company(ticker="SOMETEXTILE.NS", name="Demo Textiles Ltd", sector="textiles"))
    db_session.add(Company(ticker="RELIANCE.NS", name="Reliance Industries Ltd.", sector="oil_gas"))
    db_session.commit()

    deleted = delete_demo_companies(db_session)

    assert deleted == ["SOMETEXTILE.NS"]
    remaining = {c.ticker for c in db_session.query(Company).all()}
    assert remaining == {"RELIANCE.NS"}


def test_delete_demo_companies_is_idempotent(db_session):
    db_session.add(Company(ticker="RELIANCE.NS", name="Reliance Industries Ltd.", sector="oil_gas"))
    db_session.commit()

    assert delete_demo_companies(db_session) == []
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_integrity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.companies.integrity'`

- [ ] **Step 3: Implement**

```python
# backend/app/companies/integrity.py
"""Deterministic company-table integrity checks -- no LLM calls.

Two concerns:
1. Demo/seed rows must never resolve into a production alert. Confirmed live:
   SOMETEXTILE.NS ("Demo Textiles Ltd", from seed_feed_v2_demo.py) was
   injected into real alerts by app.companies.resolution's sector fan-out.
2. A company's sub_sector must belong to its own sector's branch of
   app.companies.sub_sectors.SUB_SECTOR_TAXONOMY (see check_sub_sectors,
   added in a later task).
"""
from sqlalchemy.orm import Session

from app.models import Company

# Explicit ticker list rather than a name-pattern heuristic: a substring
# match on "Demo" would also delete a legitimately-named company, and this
# table is production master data.
DEMO_TICKERS = frozenset({"SOMETEXTILE.NS"})


def is_demo_company(ticker: str) -> bool:
    return ticker in DEMO_TICKERS


def delete_demo_companies(session: Session) -> list[str]:
    """Deletes every demo/seed row from `companies`. Returns the tickers
    actually deleted (empty when there were none), so a caller can log a
    real result rather than assuming. Idempotent."""
    rows = session.query(Company).filter(Company.ticker.in_(DEMO_TICKERS)).all()
    deleted = [c.ticker for c in rows]
    for company in rows:
        session.delete(company)
    if deleted:
        session.commit()
    return deleted
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_integrity.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: Guard resolution against demo rows**

Add the import and the guard to `backend/app/companies/resolution.py`. At the top, alongside the existing imports:

```python
from app.companies.integrity import is_demo_company
```

Then in `_find_direct_company`, immediately after the ticker lookup succeeds, and before the name-matching fallback returns, filter demo rows. Replace the body of `_find_direct_company` from the `if mention.ticker:` line through `return None` with:

```python
    if mention.ticker:
        company = session.query(Company).filter_by(ticker=mention.ticker).one_or_none()
        if company is not None and not is_demo_company(company.ticker):
            return company
    if not mention.name:
        return None
    name_lower = mention.name.strip().lower()
    if not name_lower:
        return None
    all_companies = [c for c in session.query(Company).all() if not is_demo_company(c.ticker)]
    exact = [c for c in all_companies if c.name.strip().lower() == name_lower]
    if len(exact) == 1:
        return exact[0]
    contains = [c for c in all_companies if name_lower in c.name.lower() or c.name.lower() in name_lower]
    if len(contains) == 1:
        return contains[0]
    return None
```

And in `resolve_companies`, in the `else:` branch (the sector fan-out path), change the query to exclude demo rows:

```python
            companies = (
                session.query(Company)
                .filter_by(sector=mention.sector)
                .filter(Company.ticker.notin_(DEMO_TICKERS))
                .order_by(_TIER_RANK.asc(), Company.ticker.asc())
                .limit(TOP_N_SECTOR_COMPANIES)
                .all()
            )
```

Add `DEMO_TICKERS` to the same import line:

```python
from app.companies.integrity import DEMO_TICKERS, is_demo_company
```

- [ ] **Step 6: Write the resolution guard test**

Append to `backend/tests/test_integrity.py`:

```python
from app.analysis.schemas import CompanyMention
from app.companies.resolution import resolve_companies


def test_resolution_never_returns_a_demo_company_by_ticker(db_session):
    db_session.add(Company(ticker="SOMETEXTILE.NS", name="Demo Textiles Ltd", sector="textiles"))
    db_session.commit()

    resolved = resolve_companies(db_session, [CompanyMention(
        name="Demo Textiles Ltd", ticker="SOMETEXTILE.NS", is_direct=True,
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0,
        rationale="r", time_horizon="Short-Term",
    )])

    assert resolved == []


def test_sector_fanout_never_returns_a_demo_company(db_session):
    db_session.add(Company(ticker="SOMETEXTILE.NS", name="Demo Textiles Ltd", sector="textiles"))
    db_session.commit()

    resolved = resolve_companies(db_session, [CompanyMention(
        name="textiles sector", is_direct=False, sector="textiles",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0,
        rationale="r", time_horizon="Short-Term",
    )])

    assert resolved == []
```

- [ ] **Step 7: Run the tests**

Run: `python -m pytest tests/test_integrity.py tests/test_resolution.py -v`
Expected: PASS — all pass, including the pre-existing `test_resolution.py`

- [ ] **Step 8: Delete the live demo row**

Run: `python -c "from app.db import SessionLocal; from app.companies.integrity import delete_demo_companies; s=SessionLocal(); print('deleted:', delete_demo_companies(s)); s.close()"`
Expected: `deleted: ['SOMETEXTILE.NS']`

> If `SessionLocal` is not exported from `app.db`, check the module for the actual session factory name and use that.

- [ ] **Step 9: Run the full suite and commit**

Run: `python -m pytest`
Expected: PASS

```bash
git add backend/app/companies/integrity.py backend/app/companies/resolution.py backend/tests/test_integrity.py
git commit -m "fix: keep demo seed companies out of production alerts

SOMETEXTILE.NS (Demo Textiles Ltd, from seed_feed_v2_demo.py) was a live,
resolvable row that the sector fan-out injected into real alerts. Guards both
resolution paths and deletes the row."
```

---

## Task 3: Sector/sub-sector integrity check

Spec Section 5, deterministic half. Two live rows have a `sub_sector` that does not belong to their `sector`, and both appear in the reported bug's alert: `ASIANPAINT.NS` is `fmcg/paints` when `paints` belongs to `chemicals`, and `INDIGO.NS` is `other/aviation` when `aviation` belongs to `railways_transport`. Sub-sector-anchored fan-out (Task 9) depends on this data being coherent.

**Files:**
- Modify: `backend/app/companies/integrity.py`
- Modify: `backend/tests/test_integrity.py`
- Create: `backend/audit_taxonomy.py`

**Interfaces:**
- Consumes: `DEMO_TICKERS`, `is_demo_company` from Task 2.
- Produces:
  - `SubSectorViolation` — dataclass with `ticker: str`, `name: str`, `sector: str`, `sub_sector: str`, `correct_sector: str | None`
  - `check_sub_sectors(session) -> list[SubSectorViolation]`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_integrity.py`:

```python
from app.companies.integrity import check_sub_sectors


def test_valid_pairing_is_not_a_violation(db_session):
    db_session.add(Company(
        ticker="HINDUNILVR.NS", name="Hindustan Unilever Ltd.",
        sector="fmcg", sub_sector="personal_care",
    ))
    db_session.commit()

    assert check_sub_sectors(db_session) == []


def test_sub_sector_from_another_sector_is_a_violation(db_session):
    db_session.add(Company(
        ticker="ASIANPAINT.NS", name="Asian Paints Ltd.",
        sector="fmcg", sub_sector="paints",
    ))
    db_session.commit()

    violations = check_sub_sectors(db_session)

    assert len(violations) == 1
    assert violations[0].ticker == "ASIANPAINT.NS"
    assert violations[0].sector == "fmcg"
    assert violations[0].sub_sector == "paints"
    # "paints" appears in exactly one sector's branch, so the fix is
    # unambiguous and can be suggested.
    assert violations[0].correct_sector == "chemicals"


def test_null_sub_sector_is_not_a_violation(db_session):
    db_session.add(Company(ticker="X.NS", name="X Ltd.", sector="other", sub_sector=None))
    db_session.commit()

    assert check_sub_sectors(db_session) == []


def test_unknown_sub_sector_reports_no_suggested_sector(db_session):
    db_session.add(Company(
        ticker="Y.NS", name="Y Ltd.", sector="fmcg", sub_sector="not_a_real_subsector",
    ))
    db_session.commit()

    violations = check_sub_sectors(db_session)

    assert len(violations) == 1
    assert violations[0].correct_sector is None
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_integrity.py -k sub_sector -v`
Expected: FAIL — `ImportError: cannot import name 'check_sub_sectors'`

- [ ] **Step 3: Implement**

Append to `backend/app/companies/integrity.py`:

```python
from dataclasses import dataclass

from app.companies.sub_sectors import SUB_SECTOR_TAXONOMY


@dataclass(frozen=True)
class SubSectorViolation:
    ticker: str
    name: str
    sector: str
    sub_sector: str
    # The sector this sub_sector actually belongs to, when it appears in
    # exactly ONE sector's branch of the taxonomy (so the fix is
    # unambiguous). None when the value is unknown to the taxonomy entirely,
    # or -- not currently possible, but not assumed -- appears under more
    # than one sector.
    correct_sector: str | None


def _sector_owning(sub_sector: str) -> str | None:
    owners = [sector for sector, subs in SUB_SECTOR_TAXONOMY.items() if sub_sector in subs]
    return owners[0] if len(owners) == 1 else None


def check_sub_sectors(session: Session) -> list[SubSectorViolation]:
    """Every company whose sub_sector does not belong to its own sector's
    branch of SUB_SECTOR_TAXONOMY. A NULL sub_sector is not a violation --
    189 rows are legitimately unclassified, and the "other" sector has no
    sub-classification by design (see sub_sectors.py's module docstring).
    """
    violations = []
    rows = session.query(Company).filter(Company.sub_sector.isnot(None)).all()
    for company in rows:
        if company.sub_sector in SUB_SECTOR_TAXONOMY.get(company.sector, []):
            continue
        violations.append(SubSectorViolation(
            ticker=company.ticker, name=company.name,
            sector=company.sector, sub_sector=company.sub_sector,
            correct_sector=_sector_owning(company.sub_sector),
        ))
    return violations
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_integrity.py -v`
Expected: PASS

- [ ] **Step 5: Write the audit script**

```python
# backend/audit_taxonomy.py
"""Prints the taxonomy rows a human should eyeball, highest-leverage first.

NIFTY50 rows matter most: app.companies.resolution._TIER_RANK ranks NIFTY50
first, so a mis-tagged NIFTY50 company is the one the sector fan-out reaches
for before anything else. That is exactly how ETERNAL.NS (food delivery,
tagged fmcg/personal_care) ended up on a crude-oil story.

Read-only. Prints; never writes.
"""
from app.companies.integrity import check_sub_sectors
from app.db import SessionLocal
from app.models import Company


def main() -> None:
    session = SessionLocal()
    try:
        violations = check_sub_sectors(session)
        print(f"=== sub_sector violations ({len(violations)}) ===")
        for v in violations:
            suggestion = f" -> should be sector={v.correct_sector!r}" if v.correct_sector else " -> unknown sub_sector"
            print(f"  {v.ticker:18} {v.name[:34]:36} {v.sector}/{v.sub_sector}{suggestion}")

        print("\n=== NIFTY50 rows (review these by hand) ===")
        rows = (
            session.query(Company)
            .filter_by(index_tier="NIFTY50")
            .order_by(Company.sector.asc(), Company.ticker.asc())
            .all()
        )
        for c in rows:
            print(f"  {c.ticker:18} {c.name[:34]:36} {c.sector}/{c.sub_sector}")
        print(f"\n{len(rows)} NIFTY50 rows.")

        missing = session.query(Company).filter(Company.sub_sector.is_(None)).count()
        other = session.query(Company).filter_by(sector="other").count()
        print(f"\nunclassified sub_sector: {missing}    sector='other': {other}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the audit and fix what it reports**

Run: `python audit_taxonomy.py`
Expected: reports 2 violations (`ASIANPAINT.NS` → `chemicals`, `INDIGO.NS` → `railways_transport`), then 50 NIFTY50 rows.

Apply the two unambiguous fixes:

```bash
python -c "
from app.db import SessionLocal
from app.models import Company
s = SessionLocal()
for ticker, sector in [('ASIANPAINT.NS', 'chemicals'), ('INDIGO.NS', 'railways_transport')]:
    c = s.query(Company).filter_by(ticker=ticker).one()
    print(f'{ticker}: {c.sector} -> {sector}')
    c.sector = sector
s.commit(); s.close()
"
```

Then read the 50 NIFTY50 rows and correct any others by hand. **`ETERNAL.NS` is known-wrong**: it is tagged `fmcg/personal_care` but is a food-delivery / quick-commerce business. Set it to `fmcg/retail` (`retail` is already in the `fmcg` branch of `SUB_SECTOR_TAXONOMY`):

```bash
python -c "
from app.db import SessionLocal
from app.models import Company
s = SessionLocal()
c = s.query(Company).filter_by(ticker='ETERNAL.NS').one()
print(f'ETERNAL.NS: {c.sector}/{c.sub_sector} -> fmcg/retail')
c.sub_sector = 'retail'
s.commit(); s.close()
"
```

- [ ] **Step 7: Verify the audit is clean**

Run: `python audit_taxonomy.py`
Expected: `=== sub_sector violations (0) ===`

- [ ] **Step 8: Run the full suite and commit**

Run: `python -m pytest`
Expected: PASS

```bash
git add backend/app/companies/integrity.py backend/tests/test_integrity.py backend/audit_taxonomy.py
git commit -m "fix: validate sector/sub_sector coherence and repair known-bad rows

check_sub_sectors flags any company whose sub_sector is not in its own
sector's branch of SUB_SECTOR_TAXONOMY, suggesting the owning sector when the
value appears in exactly one branch. Found ASIANPAINT.NS as fmcg/paints
(paints belongs to chemicals) and INDIGO.NS as other/aviation -- both present
in the reported alert. audit_taxonomy.py surfaces NIFTY50 rows for review
since _TIER_RANK reaches those first."
```

---

## Task 4: Route sector-inference rows to the SECTOR_WIDE bucket

Spec Section 1, item 1. The display half of the bug: fan-out rows carry `impact_level="direct"`, so `ripple_layers.py` puts them in the DIRECT bucket, visually identical to analyzed companies.

**Files:**
- Modify: `backend/app/market/ripple_layers.py:120-131`
- Modify: `backend/tests/test_ripple_layers.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: no new symbols. Behavioural change only — an `AlertCompany` with `basis == "sector_inference"` never lands in a `DIRECT` bucket.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ripple_layers.py`. Match the fixture style already used in that file — read the top of it first and reuse its existing helpers for building an alert with companies.

```python
def test_sector_inference_row_goes_to_sector_wide_not_direct(db_session):
    # Build one alert with a direct_mention row and a sector_inference row,
    # both at impact_level="direct" -- exactly the shape _sector_fanout_mentions
    # produces for a primary sector.
    alert = _alert_with_companies(db_session, [
        {"ticker": "HPCL.NS", "sector": "oil_gas", "basis": "direct_mention",
         "impact_level": "direct", "direction": "bullish"},
        {"ticker": "ETERNAL.NS", "sector": "fmcg", "basis": "sector_inference",
         "impact_level": "direct", "direction": "bullish"},
    ])

    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())

    by_ticker = {
        row["ticker"]: layer
        for layer in layers for row in layer["rows"]
    }
    assert by_ticker["HPCL.NS"]["relationship"] == "DIRECT"
    assert by_ticker["ETERNAL.NS"]["relationship"] == "SECTOR_WIDE"


def test_every_company_still_appears_exactly_once(db_session):
    alert = _alert_with_companies(db_session, [
        {"ticker": "HPCL.NS", "sector": "oil_gas", "basis": "direct_mention",
         "impact_level": "direct", "direction": "bullish"},
        {"ticker": "ETERNAL.NS", "sector": "fmcg", "basis": "sector_inference",
         "impact_level": "direct", "direction": "bullish"},
    ])

    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())

    tickers = [row["ticker"] for layer in layers for row in layer["rows"]]
    assert sorted(tickers) == ["ETERNAL.NS", "HPCL.NS"]
```

> If `test_ripple_layers.py` has no `_alert_with_companies` helper, write one at the top of the file that creates `Company`, `Alert`, and `AlertCompany` rows from those dicts and returns the flushed `Alert`. Keep it local to the test module.

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_ripple_layers.py -k sector_wide -v`
Expected: FAIL — `assert 'DIRECT' == 'SECTOR_WIDE'`

- [ ] **Step 3: Implement the bucket dispatch change**

In `backend/app/market/ripple_layers.py`, replace lines 126-130:

```python
        engine_relation = relation_by_company_id.get(alert_company.company_id, "")
        if alert_company.impact_level == "direct":
            relationship = "DIRECT"
        else:
            relationship = relation_to_ripple_relationship(engine_relation)
```

with:

```python
        engine_relation = relation_by_company_id.get(alert_company.company_id, "")
        # basis, not impact_level, decides the bucket. A sector-inference row
        # is deterministic fan-out (app.analysis.cascade._sector_fanout_mentions
        # -> app.companies.resolution's top-N-by-tier expansion) with no
        # article-specific reasoning behind it, and it carries
        # impact_level="direct" for a PRIMARY sector -- so dispatching on
        # impact_level rendered it identically to a genuinely analyzed
        # company. Confirmed live: ETERNAL.NS (food delivery) shown as
        # "directly affected" by a crude-oil supply shock. Sector exposure is
        # still shown, but only ever in the SECTOR_WIDE bucket.
        if alert_company.basis == "sector_inference":
            relationship = "SECTOR_WIDE"
        elif alert_company.impact_level == "direct":
            relationship = "DIRECT"
        else:
            relationship = relation_to_ripple_relationship(engine_relation)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_ripple_layers.py -v`
Expected: PASS — new tests pass, existing ones still pass

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest`
Expected: PASS

```bash
git add backend/app/market/ripple_layers.py backend/tests/test_ripple_layers.py
git commit -m "fix: sector-inference rows render as sector-wide, not directly affected

Bucket dispatch keyed on basis rather than impact_level. Fan-out rows carry
impact_level=direct for a primary sector, so they were rendering identically
to analyzed companies -- ETERNAL.NS appeared as 'directly affected' by a
crude-oil supply shock. Uses the existing SECTOR_WIDE bucket; no new
category, no layout change."
```

---

## Task 5: Keep fan-out rows out of tier-1 generated layers

Spec Section 1, second half. `ripple_layers.py:180-200` lets LLM-generated layers claim tickers *before* bucket assignment runs, and `refinement.py:553` offers every company — fan-out included — to `generate_ripple_layers`. Without this, Task 4's routing is bypassed the moment tier 1 starts working (see Task 13).

**Files:**
- Modify: `backend/app/analysis/refinement.py:550-568`
- Modify: `backend/app/market/ripple_layers.py:180-200`
- Modify: `backend/tests/test_generated_ripple_layers.py`

**Interfaces:**
- Consumes: Task 4's `basis`-keyed bucket dispatch.
- Produces: no new symbols. Behavioural change only.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_generated_ripple_layers.py`, reusing that file's existing fixture helpers:

```python
def test_generated_layer_cannot_claim_a_sector_inference_row(db_session):
    alert = _alert_with_companies(db_session, [
        {"ticker": "HPCL.NS", "sector": "oil_gas", "basis": "direct_mention",
         "impact_level": "direct", "direction": "bullish"},
        {"ticker": "ETERNAL.NS", "sector": "fmcg", "basis": "sector_inference",
         "impact_level": "direct", "direction": "bullish"},
    ])
    # A generated layer that (wrongly) tries to claim the fan-out row.
    db_session.add(AlertRippleLayer(
        alert_id=alert.id, position=0, title="Losers — consumer names",
        relationship="EXPOSED", note="n",
        tickers_json=json.dumps(["HPCL.NS", "ETERNAL.NS"]),
    ))
    db_session.commit()

    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())

    by_ticker = {row["ticker"]: layer for layer in layers for row in layer["rows"]}
    assert by_ticker["HPCL.NS"]["title"] == "Losers — consumer names"
    assert by_ticker["ETERNAL.NS"]["relationship"] == "SECTOR_WIDE"
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_generated_ripple_layers.py -k cannot_claim -v`
Expected: FAIL — Eternal is claimed by the generated layer

- [ ] **Step 3: Exclude fan-out rows from generated-layer claiming**

In `backend/app/market/ripple_layers.py`, replace line 181:

```python
        index_by_ticker = {rows_flat[i]["ticker"]: i for i in remaining_indices}
```

with:

```python
        # Only analyzed rows are claimable by a generated (tier-1) layer.
        # A sector-inference row is deterministic fan-out with no
        # article-specific reasoning; letting a story-specific section claim
        # it would bypass the SECTOR_WIDE routing above and reintroduce the
        # exact misrepresentation that routing exists to prevent.
        index_by_ticker = {
            rows_flat[i]["ticker"]: i
            for i in remaining_indices
            if bucket_keys[i] != "SECTOR_WIDE"
        }
```

- [ ] **Step 4: Stop offering fan-out rows to the generator**

In `backend/app/analysis/refinement.py`, replace lines 553-562:

```python
    layer_companies = []
    for ac in alert_companies:
        company = session.get(Company, ac.company_id)
        if company is None:
            continue
        layer_companies.append({
            "ticker": company.ticker, "name": company.name,
            "sector": company.sector, "sub_sector": company.sub_sector,
            "direction": ac.direction, "why": ac.why,
        })
```

with:

```python
    # Only analyzed rows are offered for grouping. A sector-inference row is
    # deterministic fan-out (top-N-by-index-tier within a sector), so asking
    # the model to write a story-specific section around it invites exactly
    # the fabricated-specificity this pipeline avoids elsewhere -- and a
    # generated section claims tickers before bucket assignment runs
    # (app.market.ripple_layers.compute_ripple_layers), so it would also
    # bypass the SECTOR_WIDE routing. Fan-out rows always fall through to
    # the SECTOR_WIDE bucket at read time.
    layer_companies = []
    for ac in alert_companies:
        if ac.basis == "sector_inference":
            continue
        company = session.get(Company, ac.company_id)
        if company is None:
            continue
        layer_companies.append({
            "ticker": company.ticker, "name": company.name,
            "sector": company.sector, "sub_sector": company.sub_sector,
            "direction": ac.direction, "why": ac.why,
        })
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_generated_ripple_layers.py tests/test_ripple_layers.py tests/test_refinement.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite and commit**

Run: `python -m pytest`
Expected: PASS

```bash
git add backend/app/market/ripple_layers.py backend/app/analysis/refinement.py backend/tests/test_generated_ripple_layers.py
git commit -m "fix: tier-1 generated layers can no longer claim fan-out rows

Generated layers claim tickers before bucket assignment, and refine_alert
offered every company to generate_ripple_layers -- so a story-specific
section could sort a sector-inference row into itself and bypass the
SECTOR_WIDE routing entirely. Both ends closed."
```

---

## Task 6: Drop template rationales and apply a confidence floor

Spec Section 1, items 2 and 3. A fan-out row currently persists a rationale that reads like analysis (`"Sector-wide exposure via fmcg: Higher crude inflates packaging materials..."`). The floor is deliberately minor — measured on production data it removes 20 rows of 881 — and is not the relevance defence.

**Files:**
- Modify: `backend/app/companies/resolution.py`
- Modify: `backend/app/pipeline.py`
- Modify: `backend/tests/test_resolution.py`
- Modify: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `CONFIDENCE_FLOOR: int` in `app/pipeline.py`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_resolution.py`:

```python
def test_sector_inference_entry_has_no_rationale(db_session):
    db_session.add(Company(ticker="ITC.NS", name="ITC Ltd.", sector="fmcg", index_tier="NIFTY50"))
    db_session.commit()

    resolved = resolve_companies(db_session, [CompanyMention(
        name="fmcg sector", is_direct=False, sector="fmcg",
        direction="bullish", magnitude_low=1.0, magnitude_high=3.0,
        rationale="Sector-wide exposure via fmcg: some template text",
        time_horizon="Short-Term",
    )])

    assert len(resolved) == 1
    assert resolved[0]["basis"] == "sector_inference"
    assert resolved[0]["rationale"] is None


def test_direct_mention_keeps_its_rationale(db_session):
    db_session.add(Company(ticker="HPCL.NS", name="Hindustan Petroleum Corporation", sector="oil_gas"))
    db_session.commit()

    resolved = resolve_companies(db_session, [CompanyMention(
        name="Hindustan Petroleum Corporation", ticker="HPCL.NS", is_direct=True,
        direction="bullish", magnitude_low=1.0, magnitude_high=3.0,
        rationale="Real, article-specific reasoning.", time_horizon="Short-Term",
    )])

    assert resolved[0]["rationale"] == "Real, article-specific reasoning."
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_resolution.py -k rationale -v`
Expected: FAIL — rationale is the template string, not None

- [ ] **Step 3: Implement the rationale change**

In `backend/app/companies/resolution.py`, change `_to_resolved`'s signature and rationale line. Replace:

```python
def _to_resolved(
    company: Company, mention: CompanyMention, basis: str,
    impact_level: str = "direct", parent_company_id: int | None = None,
) -> dict:
    return {
        "company_id": company.id,
        "direction": mention.direction,
        "magnitude_low": mention.magnitude_low,
        "magnitude_high": mention.magnitude_high,
        "rationale": mention.rationale,
```

with:

```python
def _to_resolved(
    company: Company, mention: CompanyMention, basis: str,
    impact_level: str = "direct", parent_company_id: int | None = None,
) -> dict:
    return {
        "company_id": company.id,
        "direction": mention.direction,
        "magnitude_low": mention.magnitude_low,
        "magnitude_high": mention.magnitude_high,
        # A sector-inference row's "rationale" is a template built from the
        # sector's own one-line mechanism (app.analysis.cascade.
        # _sector_fanout_mentions), not reasoning about THIS company -- and
        # it reads exactly like analysis, which is how a food-delivery
        # company came to carry a paragraph about crude-driven packaging
        # costs. Persist nothing rather than something that misrepresents
        # itself; the row still renders as a flagged exposure via
        # app.reasoning.ripple_relationship.is_exposure_only.
        "rationale": None if basis == "sector_inference" else mention.rationale,
```

- [ ] **Step 4: Make the column nullable**

`backend/app/models.py:121` is currently `rationale = Column(Text, nullable=False)`, so persisting `None` raises an `IntegrityError`. Change it to:

```python
    # Nullable since the precision work: a sector_inference row persists no
    # rationale at all (app.companies.resolution._to_resolved), and a row
    # whose direction was flipped by measurement has its now-contradictory
    # rationale cleared (app.pipeline._persist_alert). Both are "show
    # nothing rather than something misleading", not missing data.
    rationale = Column(Text, nullable=True)
```

Tests use SQLite and rebuild the schema per run, so they pick this up automatically. **Production Postgres does not** — run this against production before deploying:

```sql
ALTER TABLE alert_companies ALTER COLUMN rationale DROP NOT NULL;
```

> Translation is unaffected: `app/translation/job.py:68` already substitutes `""` and never reads `AlertCompany.rationale`.

- [ ] **Step 5: Null-guard the frontend readers**

`frontend/src/lib/api.ts:44` types this field as non-nullable and two components pass it directly into string functions. This is a null-safety fix, **not** a layout or design change — the rendered output for a row that has a rationale is byte-identical.

In `frontend/src/lib/api.ts`, change line 44:

```ts
  rationale: string | null; // null for sector_inference rows and for rows whose direction measurement flipped
```

In `frontend/src/components/InsightCard.tsx:80`:

```tsx
  const points_ = company.key_points.length > 0
    ? company.key_points
    : (company.rationale ? [truncatedRationale(company.rationale)] : []);
```

In `frontend/src/components/ReasoningPanel.tsx:25`:

```tsx
  const points = company.key_points.length > 0
    ? company.key_points
    : (company.rationale ? splitRationaleIntoPoints(company.rationale) : []);
```

Check `frontend/src/features/visualize/charts/ImpactTree.tsx:36` too — `truncatedRationale(top.rationale)` sits behind a `??`, so confirm whether `top.rationale` can now be null there and guard it the same way if so.

> `frontend/src/v3/Sheets.tsx:224` already null-checks and needs no change.

- [ ] **Step 6: Run the resolution tests**

Run: `python -m pytest tests/test_resolution.py -v`
Expected: PASS

Run the frontend checks too: `cd ../frontend && npm run typecheck && npm test`
Expected: PASS — the type change surfaces any other unguarded reader.

- [ ] **Step 7: Write the failing confidence-floor test**

Append to `backend/tests/test_pipeline.py`:

```python
from app.pipeline import CONFIDENCE_FLOOR


def test_entries_below_the_confidence_floor_are_not_persisted(db_session, monkeypatch):
    # compute_confidence is deterministic; force a below-floor score rather
    # than trying to construct inputs that happen to produce one.
    import app.pipeline as pipeline_module
    from app.reasoning.confidence import ConfidenceResult

    monkeypatch.setattr(
        pipeline_module, "compute_confidence",
        lambda **kwargs: ConfidenceResult(score=CONFIDENCE_FLOOR - 1, band="LOW"),
    )

    article = _article(db_session)
    company = Company(ticker="X.NS", name="X Ltd.", sector="other")
    db_session.add(company)
    db_session.commit()

    alert = _persist_alert(db_session, article, "other", [{
        "company_id": company.id, "direction": "bullish",
        "magnitude_low": 1.0, "magnitude_high": 2.0, "rationale": "r",
        "key_points": [], "basis": "direct_mention", "time_horizon": "Short-Term",
        "impact_level": "direct",
    }])

    assert alert.companies == []


def test_entries_at_the_confidence_floor_are_persisted(db_session, monkeypatch):
    import app.pipeline as pipeline_module
    from app.reasoning.confidence import ConfidenceResult

    monkeypatch.setattr(
        pipeline_module, "compute_confidence",
        lambda **kwargs: ConfidenceResult(score=CONFIDENCE_FLOOR, band="MODERATE"),
    )

    article = _article(db_session)
    company = Company(ticker="X.NS", name="X Ltd.", sector="other")
    db_session.add(company)
    db_session.commit()

    alert = _persist_alert(db_session, article, "other", [{
        "company_id": company.id, "direction": "bullish",
        "magnitude_low": 1.0, "magnitude_high": 2.0, "rationale": "r",
        "key_points": [], "basis": "direct_mention", "time_horizon": "Short-Term",
        "impact_level": "direct",
    }])

    assert len(alert.companies) == 1
```

> Reuse `test_pipeline.py`'s existing article fixture rather than writing `_article` if one is already present. Read the file first.

- [ ] **Step 8: Run it to make sure it fails**

Run: `python -m pytest tests/test_pipeline.py -k confidence_floor -v`
Expected: FAIL — `ImportError: cannot import name 'CONFIDENCE_FLOOR'`

- [ ] **Step 9: Implement the floor**

In `backend/app/pipeline.py`, add below `LEVEL_CONFIDENCE_MULTIPLIER`:

```python
# Minimum confidence_score for an AlertCompany row to be persisted.
#
# Deliberately modest, and NOT the relevance defence. Measured on production
# data, a floor of 40 removes 20 rows of 881 -- and only 16 of 557
# sector_inference rows (2%), the exact category that produced the reported
# bug. Median confidence_score is 50 at every impact level because
# calibration (weight 0.30) and rulebook match (0.20) contribute 0.0 for
# nearly every row, so half the weight is inert and scores cluster. Raising
# the floor to 50 would cut correct direct_mention rows at the median while
# still keeping half the fan-out.
#
# Relevance is enforced structurally instead: basis-keyed bucketing
# (app.market.ripple_layers), candidate grounding (app.companies.candidates),
# and the per-company verification pass (app.analysis.verification). This
# floor only trims the degenerate tail.
CONFIDENCE_FLOOR = 40
```

Then in `_persist_alert`, replace the entry loop:

```python
    alert_companies = []
    for entry in entries:
        alert_company = _build_alert_company(session, alert.id, article, category, entry)
        session.add(alert_company)
        alert_companies.append(alert_company)
```

with:

```python
    alert_companies = []
    kept_entries = []
    for entry in entries:
        alert_company = _build_alert_company(session, alert.id, article, category, entry)
        if alert_company.confidence_score < CONFIDENCE_FLOOR:
            logger.info(
                "dropping company_id=%s from alert_id=%s: confidence %s below floor %s",
                entry["company_id"], alert.id, alert_company.confidence_score, CONFIDENCE_FLOOR,
            )
            continue
        session.add(alert_company)
        alert_companies.append(alert_company)
        kept_entries.append(entry)
    entries = kept_entries
```

> Reassigning `entries` matters: the `market_moves` loop directly below iterates `entries` and would otherwise measure companies that were just dropped.

- [ ] **Step 10: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 11: Run the full suite and commit**

Run: `python -m pytest`
Expected: PASS

```bash
git add backend/app/companies/resolution.py backend/app/pipeline.py backend/app/models.py backend/tests/test_resolution.py backend/tests/test_pipeline.py frontend/src/lib/api.ts frontend/src/components/InsightCard.tsx frontend/src/components/ReasoningPanel.tsx
git commit -m "fix: drop template rationales on fan-out rows, add a confidence floor

A sector-inference row's rationale was a template built from the sector's
one-line mechanism, and read exactly like per-company analysis. Persist None
instead; the row still renders as a flagged exposure.

CONFIDENCE_FLOOR=40 is a modest tail trim, not the relevance defence -- on
production data it removes 20 of 881 rows and only 2% of fan-out rows, since
scores cluster at 50 with half the weight inert.

AlertCompany.rationale becomes nullable. Production Postgres needs
ALTER TABLE alert_companies ALTER COLUMN rationale DROP NOT NULL before
deploy. Frontend readers null-guarded -- no layout change; a row that has a
rationale renders identically."
```

---

## Task 7: Candidate retrieval

Spec Section 2, items 1 and 2. The model currently names companies from memory with no candidate list — the standard hallucination setup, and also why 61% of alerts come back empty.

**Files:**
- Create: `backend/app/companies/candidates.py`
- Create: `backend/tests/test_candidates.py`

**Interfaces:**
- Consumes: `DEMO_TICKERS` from Task 2.
- Produces:
  - `MAX_CANDIDATES_PER_SECTOR: int`
  - `candidate_companies(session, sectors: list[str], limit_per_sector: int = MAX_CANDIDATES_PER_SECTOR) -> list[Company]`
  - `format_candidates(companies: list[Company]) -> str`
  - `candidate_tickers(companies: list[Company]) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_candidates.py
from app.companies.candidates import (
    candidate_companies, candidate_tickers, format_candidates,
)
from app.models import Company


def _seed(db_session, rows):
    for ticker, name, sector, tier, desc in rows:
        db_session.add(Company(
            ticker=ticker, name=name, sector=sector, index_tier=tier, business_desc=desc,
        ))
    db_session.commit()


def test_returns_companies_only_for_the_named_sectors(db_session):
    _seed(db_session, [
        ("HPCL.NS", "Hindustan Petroleum", "oil_gas", "NIFTY50", "Refines crude oil."),
        ("ITC.NS", "ITC Ltd.", "fmcg", "NIFTY50", "Sells cigarettes and packaged foods."),
    ])

    result = candidate_companies(db_session, ["oil_gas"])

    assert [c.ticker for c in result] == ["HPCL.NS"]


def test_orders_by_index_tier_so_prominent_names_survive_the_limit(db_session):
    _seed(db_session, [
        ("SMALL.NS", "Small Oil Ltd.", "oil_gas", "NIFTYSMALLCAP250", "A small refiner."),
        ("BIG.NS", "Big Oil Ltd.", "oil_gas", "NIFTY50", "A large refiner."),
    ])

    result = candidate_companies(db_session, ["oil_gas"], limit_per_sector=1)

    assert [c.ticker for c in result] == ["BIG.NS"]


def test_excludes_demo_companies(db_session):
    _seed(db_session, [
        ("SOMETEXTILE.NS", "Demo Textiles Ltd", "textiles", "NIFTY50", "Demo."),
    ])

    assert candidate_companies(db_session, ["textiles"]) == []


def test_deduplicates_across_repeated_sectors(db_session):
    _seed(db_session, [("HPCL.NS", "Hindustan Petroleum", "oil_gas", "NIFTY50", "Refines crude oil.")])

    result = candidate_companies(db_session, ["oil_gas", "oil_gas"])

    assert [c.ticker for c in result] == ["HPCL.NS"]


def test_format_includes_ticker_name_subsector_and_description(db_session):
    _seed(db_session, [("HPCL.NS", "Hindustan Petroleum", "oil_gas", "NIFTY50", "Refines crude oil.")])
    company = candidate_companies(db_session, ["oil_gas"])[0]
    company.sub_sector = "refining_marketing"

    text = format_candidates([company])

    assert "HPCL.NS" in text
    assert "Hindustan Petroleum" in text
    assert "refining_marketing" in text
    assert "Refines crude oil." in text


def test_format_handles_a_company_with_no_description(db_session):
    _seed(db_session, [("X.NS", "X Ltd.", "oil_gas", None, None)])
    company = candidate_companies(db_session, ["oil_gas"])[0]

    text = format_candidates([company])

    assert "X.NS" in text
    assert "None" not in text


def test_candidate_tickers_returns_plain_strings(db_session):
    _seed(db_session, [("HPCL.NS", "Hindustan Petroleum", "oil_gas", "NIFTY50", "Refines crude oil.")])

    assert candidate_tickers(candidate_companies(db_session, ["oil_gas"])) == ["HPCL.NS"]


def test_empty_sector_list_returns_nothing(db_session):
    assert candidate_companies(db_session, []) == []
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_candidates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.companies.candidates'`

- [ ] **Step 3: Implement**

```python
# backend/app/companies/candidates.py
"""Real-company candidate retrieval for the analysis prompts.

Without this the model names companies purely from parametric memory: it has
no list to select from, so it both invents links (a food-delivery company on
a crude-oil story) and returns nothing at all when it cannot recall a name
(61% of alerts had zero companies). Giving it the actual DB rows -- ticker,
name, sub-sector, and one-line business description -- converts the task from
recall to selection, and lets the tool schema enum-constrain `ticker` to
tickers that provably resolve.

Ordering is by index tier so that, when a sector has more companies than the
limit, the ones that survive are the prominent, liquid names an analyst would
actually consider -- same _TIER_RANK discipline as app.companies.resolution.
"""
from sqlalchemy import case
from sqlalchemy.orm import Session

from app.companies.integrity import DEMO_TICKERS
from app.models import Company

# Per sector. Large enough that a real answer is almost always present,
# small enough that several sectors still fit one prompt alongside the
# rationale instructions.
MAX_CANDIDATES_PER_SECTOR = 40

_TIER_RANK = case(
    (Company.index_tier == "NIFTY50", 0),
    (Company.index_tier == "NIFTYNEXT50", 1),
    (Company.index_tier == "NIFTYMIDCAP150", 2),
    (Company.index_tier == "NIFTYSMALLCAP250", 3),
    else_=4,
)


def candidate_companies(
    session: Session, sectors: list[str], limit_per_sector: int = MAX_CANDIDATES_PER_SECTOR,
) -> list[Company]:
    """Every plausible company for the given sectors, most prominent first,
    deduplicated by ticker across sectors and with demo/seed rows excluded.
    Order is stable (tier, then ticker) so the same inputs always produce the
    same prompt -- a prompt that reshuffles between runs makes a regression
    impossible to attribute."""
    seen: set[str] = set()
    result: list[Company] = []
    for sector in sectors:
        rows = (
            session.query(Company)
            .filter_by(sector=sector)
            .filter(Company.ticker.notin_(DEMO_TICKERS))
            .order_by(_TIER_RANK.asc(), Company.ticker.asc())
            .limit(limit_per_sector)
            .all()
        )
        for company in rows:
            if company.ticker in seen:
                continue
            seen.add(company.ticker)
            result.append(company)
    return result


def format_candidates(companies: list[Company]) -> str:
    """One line per company for prompt injection. A missing sub_sector or
    business_desc is omitted rather than rendered as "None" -- a literal
    "None" in the prompt reads as a real value to the model."""
    lines = []
    for company in companies:
        parts = [f"- {company.ticker} ({company.name}"]
        if company.sub_sector:
            parts.append(f", {company.sub_sector}")
        parts.append(")")
        line = "".join(parts)
        if company.business_desc:
            line += f": {company.business_desc}"
        lines.append(line)
    return "\n".join(lines)


def candidate_tickers(companies: list[Company]) -> list[str]:
    return [c.ticker for c in companies]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_candidates.py -v`
Expected: PASS — 8 passed

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest`
Expected: PASS

```bash
git add backend/app/companies/candidates.py backend/tests/test_candidates.py
git commit -m "feat: real-company candidate retrieval for analysis prompts

Converts company identification from recall to selection. Returns DB rows for
the named sectors ordered by index tier, formatted with sub-sector and
business description, plus the ticker list for enum-constraining the tool
schema. Demo rows excluded; ordering is stable so prompts are reproducible."
```

---

## Task 8: Ground company identification in the candidate list

Spec Section 2, items 2 and 3. Wires Task 7 into `cascade.py::_identify_companies`.

**Files:**
- Modify: `backend/app/analysis/cascade.py`
- Modify: `backend/tests/test_cascade.py`

**Interfaces:**
- Consumes: `candidate_companies`, `format_candidates`, `candidate_tickers` from Task 7.
- Produces:
  - `build_company_tool(parent_tickers: list[str] | None, valid_tickers: list[str] | None = None) -> dict`
  - `_identify_companies(client, facts, sectors, impact_level, parent_pool, session=None) -> list[CompanyMention]`
  - `analyze_article(client, title, content, session=None) -> AnalysisOutput`

Every new parameter defaults to `None` so existing callers and tests keep working ungrounded.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_cascade.py`, following that file's existing fake-client pattern:

```python
def test_company_tool_enum_constrains_ticker_to_candidates():
    tool = build_company_tool(None, valid_tickers=["HPCL.NS", "BPCL.NS"])
    ticker_schema = (
        tool["function"]["parameters"]["properties"]["sector_companies"]
        ["items"]["properties"]["companies"]["items"]["properties"]["ticker"]
    )
    assert ticker_schema["enum"] == ["HPCL.NS", "BPCL.NS"]


def test_company_tool_leaves_ticker_unconstrained_without_candidates():
    tool = build_company_tool(None)
    ticker_schema = (
        tool["function"]["parameters"]["properties"]["sector_companies"]
        ["items"]["properties"]["companies"]["items"]["properties"]["ticker"]
    )
    assert "enum" not in ticker_schema


def test_identify_companies_injects_candidates_into_the_prompt(db_session):
    db_session.add(Company(
        ticker="HPCL.NS", name="Hindustan Petroleum", sector="oil_gas",
        index_tier="NIFTY50", business_desc="Refines crude oil.",
    ))
    db_session.commit()

    client = _fake_client_returning({"sector_companies": []})
    _identify_companies(
        client, "facts", [SectorFinding(sector="oil_gas", direction="bullish", mechanism="m")],
        impact_level="direct", parent_pool=None, session=db_session,
    )

    prompt = client.last_kwargs["messages"][1]["content"]
    assert "HPCL.NS" in prompt
    assert "Refines crude oil." in prompt


def test_identify_companies_drops_a_ticker_outside_the_candidate_list(db_session):
    db_session.add(Company(
        ticker="HPCL.NS", name="Hindustan Petroleum", sector="oil_gas", index_tier="NIFTY50",
    ))
    db_session.commit()

    client = _fake_client_returning({"sector_companies": [{
        "sector": "oil_gas",
        "companies": [
            _company_payload(name="Hindustan Petroleum", ticker="HPCL.NS"),
            # Provider enums are not reliably enforced for nested array
            # items (cascade.py:282) -- the defensive filter must catch this.
            _company_payload(name="Invented Ltd.", ticker="INVENTED.NS"),
        ],
    }]})

    mentions = _identify_companies(
        client, "facts", [SectorFinding(sector="oil_gas", direction="bullish", mechanism="m")],
        impact_level="direct", parent_pool=None, session=db_session,
    )

    assert [m.ticker for m in mentions] == ["HPCL.NS"]


def test_identify_companies_without_a_session_stays_ungrounded(db_session):
    client = _fake_client_returning({"sector_companies": [{
        "sector": "oil_gas",
        "companies": [_company_payload(name="Anything Ltd.", ticker="ANY.NS")],
    }]})

    mentions = _identify_companies(
        client, "facts", [SectorFinding(sector="oil_gas", direction="bullish", mechanism="m")],
        impact_level="direct", parent_pool=None,
    )

    assert [m.ticker for m in mentions] == ["ANY.NS"]
```

> `_fake_client_returning` and `_company_payload` are helpers this test file needs. If `test_cascade.py` has equivalents, use those names instead. Otherwise add at the top of the file:
>
> ```python
> import json
> from types import SimpleNamespace
>
>
> class _FakeClient:
>     def __init__(self, payload):
>         self._payload = payload
>         self.last_kwargs = None
>         self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
>
>     def _create(self, **kwargs):
>         self.last_kwargs = kwargs
>         name = kwargs["tool_choice"]["function"]["name"]
>         return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
>             tool_calls=[SimpleNamespace(function=SimpleNamespace(
>                 name=name, arguments=json.dumps(self._payload),
>             ))],
>         ))])
>
>
> def _fake_client_returning(payload):
>     return _FakeClient(payload)
>
>
> def _company_payload(*, name, ticker):
>     return {
>         "name": name, "ticker": ticker, "direction": "bullish",
>         "magnitude_low": 1.0, "magnitude_high": 3.0, "rationale": "r",
>         "key_points": [], "time_horizon": "Short-Term", "reasons": [],
>         "evidence_refs": [], "risks": [], "assumptions": [], "unknowns": [],
>         "alternative_hypothesis": "none",
>     }
> ```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_cascade.py -k candidate -v`
Expected: FAIL — `build_company_tool() got an unexpected keyword argument 'valid_tickers'`

- [ ] **Step 3: Add the enum constraint to the tool builder**

In `backend/app/analysis/cascade.py`, replace `build_company_tool`:

```python
def build_company_tool(parent_tickers: list[str] | None, valid_tickers: list[str] | None = None) -> dict:
    """parent_tickers=None builds the direct/primary-stage tool (stage 3, no
    parent_ticker field). A non-empty list builds a cascade-stage tool
    (stages 5/7), adding a parent_ticker field enum-constrained to
    parent_tickers so the model cannot invent a nonexistent parent.

    valid_tickers, when given, enum-constrains `ticker` to companies that
    actually exist in the database (see app.companies.candidates) -- the
    model selects from real rows instead of recalling a symbol. Left
    unconstrained (nullable string) when None, preserving the ungrounded
    behavior for callers with no DB session.
    """
    properties = dict(_COMPANY_ITEM_PROPERTIES)
    required = list(_COMPANY_ITEM_REQUIRED)
    if valid_tickers:
        properties["ticker"] = {"type": "string", "enum": valid_tickers}
    if parent_tickers:
        properties["parent_ticker"] = {"type": "string", "enum": parent_tickers}
        required.append("parent_ticker")
    return {
        "type": "function",
        "function": {
            "name": "record_sector_companies",
            "description": "Record companies affected within each given sector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector_companies": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sector": {"type": "string", "enum": SECTORS},
                                "companies": {
                                    "type": "array",
                                    "items": {
                                        "type": "object", "properties": properties, "required": required,
                                    },
                                },
                            },
                            "required": ["sector", "companies"],
                        },
                    },
                },
                "required": ["sector_companies"],
            },
        },
    }
```

- [ ] **Step 4: Wire candidates into `_identify_companies`**

Add the import at the top of `cascade.py`:

```python
from app.companies.candidates import candidate_companies, candidate_tickers, format_candidates
```

Change the signature:

```python
def _identify_companies(
    client, facts: str, sectors: list[SectorFinding], impact_level: str,
    parent_pool: list[CompanyMention] | None, session=None,
) -> list[CompanyMention]:
```

Immediately before the `rationale_instructions = ...` line, insert:

```python
    # Grounding (see app.companies.candidates): give the model the real
    # companies in these sectors so it selects rather than recalls. session
    # is None for callers with no DB (older tests) -- those stay ungrounded.
    valid_tickers: list[str] | None = None
    candidate_block = ""
    if session is not None:
        candidates = candidate_companies(session, [s.sector for s in sectors])
        if candidates:
            valid_tickers = candidate_tickers(candidates)
            candidate_block = (
                "\n\nCANDIDATE COMPANIES -- choose ONLY from this list. These are "
                "the real, tradeable companies in the sectors above, with what "
                "each actually does. A company not in this list cannot be "
                "recorded, so do not name one. Selecting NONE of them for a "
                "sector is a correct answer when none genuinely fits.\n"
                + format_candidates(candidates)
            )
```

Then add `candidate_block` to the message content. Replace:

```python
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{framing}\n\n"
                f"Facts: {facts}\n\n"
                f"Sectors:\n{sector_lines}"
                f"{parent_context}\n\n"
                f"{rationale_instructions}"
            ),
        },
    ]
    tool = build_company_tool(parent_tickers if parent_tickers else None)
```

with:

```python
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{framing}\n\n"
                f"Facts: {facts}\n\n"
                f"Sectors:\n{sector_lines}"
                f"{parent_context}"
                f"{candidate_block}\n\n"
                f"{rationale_instructions}"
            ),
        },
    ]
    tool = build_company_tool(parent_tickers if parent_tickers else None, valid_tickers=valid_tickers)
```

The slim-retry path further down rebuilds `messages[1]["content"]` and must carry the block too. Replace:

```python
        messages[1]["content"] = (
            f"{framing}\n\n"
            f"Facts: {facts}\n\n"
            f"Sectors:\n{sector_lines}"
            f"{parent_context}\n\n"
            f"{CASCADE_COMPANY_RATIONALE_INSTRUCTIONS}"
        )
```

with:

```python
        messages[1]["content"] = (
            f"{framing}\n\n"
            f"Facts: {facts}\n\n"
            f"Sectors:\n{sector_lines}"
            f"{parent_context}"
            f"{candidate_block}\n\n"
            f"{CASCADE_COMPANY_RATIONALE_INSTRUCTIONS}"
        )
```

- [ ] **Step 5: Add the defensive post-filter**

In the same function, replace the mention-building loop:

```python
    mentions: list[CompanyMention] = []
    for group in arguments.get("sector_companies", []):
        sector = group.get("sector")
        for company in group.get("companies", []):
            mentions.append(CompanyMention(
```

with:

```python
    # Provider-side enum enforcement is not reliable for nested array items
    # (see the SECTORS filter at the end of _identify_sectors for the same
    # failure mode confirmed in production). When grounding is active, drop
    # any ticker outside the candidate list rather than letting an invented
    # symbol through to resolution.
    allowed = set(valid_tickers) if valid_tickers else None

    mentions: list[CompanyMention] = []
    for group in arguments.get("sector_companies", []):
        sector = group.get("sector")
        for company in group.get("companies", []):
            if allowed is not None and company.get("ticker") not in allowed:
                logger.warning(
                    "dropping off-candidate ticker %r (%r) from grounded company stage",
                    company.get("ticker"), company.get("name"),
                )
                continue
            mentions.append(CompanyMention(
```

- [ ] **Step 6: Thread `session` through the callers**

In `_identify_cascade_companies_per_sector`, add `session=None` to the signature and pass it through:

```python
def _identify_cascade_companies_per_sector(
    client, facts: str, sectors: list[SectorFinding], impact_level: str,
    parent_pool: list[CompanyMention], session=None,
) -> tuple[list[CompanyMention], list[dict]]:
```

and inside the retry loop:

```python
                mentions.extend(_identify_companies(
                    client, facts, [sector], impact_level=impact_level,
                    parent_pool=parent_pool, session=session,
                ))
```

In `analyze_article`, add `session=None` to the signature and pass it to all three call sites (`primary_companies`, the L1 call, the L2 call):

```python
def analyze_article(client, title: str, content: str, session=None) -> AnalysisOutput:
```

```python
        primary_companies = _identify_companies(
            client, facts_result.facts, primary_sectors, impact_level="direct",
            parent_pool=None, session=session,
        )
```

```python
            l1_companies, l1_gaps = _identify_cascade_companies_per_sector(
                client, facts_result.facts, l1_sectors, impact_level="indirect_l1",
                parent_pool=l1_parent_tickers_present, session=session,
            )
```

```python
                l2_companies, l2_gaps = _identify_cascade_companies_per_sector(
                    client, facts_result.facts, l2_sectors, impact_level="indirect_l2",
                    parent_pool=l2_parent_tickers_present, session=session,
                )
```

In `backend/app/pipeline.py::process_new_articles`, pass the session:

```python
                    analysis = analyze_article(claude_client, article.title, article_text(article), session=session)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_cascade.py tests/test_pipeline.py tests/test_end_to_end.py -v`
Expected: PASS

- [ ] **Step 8: Run the full suite and commit**

Run: `python -m pytest`
Expected: PASS

```bash
git add backend/app/analysis/cascade.py backend/app/pipeline.py backend/tests/test_cascade.py
git commit -m "feat: ground company identification in real DB candidates

_identify_companies now injects the actual companies for the named sectors
(ticker, name, sub-sector, business description) and enum-constrains ticker
to that list, converting the task from recall to selection. Adds a defensive
post-filter since provider enums are not reliably enforced for nested array
items. session defaults to None, so ungrounded callers are unchanged."
```

---

## Task 9: Backfill business descriptions

Spec Section 2, item 1. Task 7's candidate list is far more useful with descriptions: 13 of 1017 companies have one. This task is operational — run the existing script, verify coverage.

**Files:**
- Modify: `backend/backfill_business_profiles.py` (only if it lacks resumability)

**Interfaces:**
- Consumes: nothing.
- Produces: populated `Company.business_desc` rows. No new symbols.

- [ ] **Step 1: Read the existing script**

Run: `cat backfill_business_profiles.py`

Confirm it (a) skips companies that already have a `business_desc`, (b) batches, and (c) commits incrementally. If any is missing, add it — a free-tier run over ~1000 companies will be interrupted, and restarting from zero wastes quota.

- [ ] **Step 2: Check current coverage**

```bash
python -c "
from app.db import SessionLocal
from app.models import Company
s = SessionLocal()
total = s.query(Company).count()
have = s.query(Company).filter(Company.business_desc.isnot(None)).count()
print(f'{have}/{total} have business_desc')
s.close()
"
```
Expected: `13/1016` (1016 after the demo row deletion in Task 2)

- [ ] **Step 3: Run the backfill**

Run: `python backfill_business_profiles.py`

Expect this to take a long time on free-tier quotas and to need several runs. Re-run until coverage stops increasing.

- [ ] **Step 4: Verify coverage improved**

Re-run the Step 2 command.
Expected: coverage well above 13. Anything above ~80% is good; 100% is not required — `format_candidates` omits a missing description cleanly.

- [ ] **Step 5: Spot-check quality on the names that matter most**

```bash
python -c "
from app.db import SessionLocal
from app.models import Company
s = SessionLocal()
for t in ['ETERNAL.NS','ASIANPAINT.NS','HINDUNILVR.NS','INDIGO.NS','HPCL.NS','ITC.NS']:
    c = s.query(Company).filter_by(ticker=t).one_or_none()
    if c: print(f'{t:16} {c.sector}/{c.sub_sector}: {c.business_desc}')
s.close()
"
```

Read the output. `ETERNAL.NS` must describe food delivery / quick commerce — that description is what teaches the model it has no crude-oil mechanism. If it is wrong or generic, fix that row by hand.

- [ ] **Step 6: Commit any script changes**

```bash
git add backend/backfill_business_profiles.py
git commit -m "chore: make business-profile backfill resumable

A free-tier run over ~1000 companies gets interrupted; skipping already-
enriched rows and committing incrementally means a restart resumes instead of
re-spending quota."
```

> If the script needed no changes, skip the commit. The database rows are the deliverable here, not code.

---

## Task 10: Per-company verification pass

Spec Section 3. Nothing currently re-reads the assembled company list and asks whether each company belongs.

**Files:**
- Create: `backend/app/analysis/verification.py`
- Create: `backend/tests/test_verification.py`
- Modify: `backend/app/analysis/cascade.py`

**Interfaces:**
- Consumes: `CompanyMention` from `app.analysis.schemas`.
- Produces:
  - `build_verification_tool(valid_tickers: list[str]) -> dict`
  - `verify_companies(client, facts: str, title: str, companies: list[CompanyMention]) -> list[CompanyMention]`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_verification.py
import json
from types import SimpleNamespace

from app.analysis.schemas import CompanyMention
from app.analysis.verification import build_verification_tool, verify_companies


class _FakeClient:
    def __init__(self, payload, raises=None):
        self._payload = payload
        self._raises = raises
        self.calls = 0
        self.last_kwargs = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self._raises is not None:
            raise self._raises
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            tool_calls=[SimpleNamespace(function=SimpleNamespace(
                name="record_company_verdicts", arguments=json.dumps(self._payload),
            ))],
        ))])


def _mention(ticker, name="X Ltd."):
    return CompanyMention(
        name=name, ticker=ticker, is_direct=True, sector="oil_gas",
        direction="bullish", magnitude_low=1.0, magnitude_high=3.0,
        rationale="r", time_horizon="Short-Term",
    )


def test_tool_enum_constrains_tickers_to_the_assembled_list():
    tool = build_verification_tool(["A.NS", "B.NS"])
    ticker_schema = (
        tool["function"]["parameters"]["properties"]["verdicts"]
        ["items"]["properties"]["ticker"]
    )
    assert ticker_schema["enum"] == ["A.NS", "B.NS"]


def test_a_company_marked_not_belonging_is_dropped():
    client = _FakeClient({"verdicts": [
        {"ticker": "A.NS", "belongs": True},
        {"ticker": "B.NS", "belongs": False, "reason": "no mechanism reaches it"},
    ]})

    kept = verify_companies(client, "facts", "title", [_mention("A.NS"), _mention("B.NS")])

    assert [m.ticker for m in kept] == ["A.NS"]


def test_a_company_the_model_never_judged_is_kept():
    # Omission is not a rejection -- same "omit rather than mismatch"
    # discipline as generate_impact_whys.
    client = _FakeClient({"verdicts": [{"ticker": "A.NS", "belongs": True}]})

    kept = verify_companies(client, "facts", "title", [_mention("A.NS"), _mention("B.NS")])

    assert [m.ticker for m in kept] == ["A.NS", "B.NS"]


def test_a_verdict_for_an_unknown_ticker_is_ignored():
    client = _FakeClient({"verdicts": [{"ticker": "GHOST.NS", "belongs": False}]})

    kept = verify_companies(client, "facts", "title", [_mention("A.NS")])

    assert [m.ticker for m in kept] == ["A.NS"]


def test_a_failed_call_keeps_every_company():
    client = _FakeClient(None, raises=RuntimeError("provider down"))

    kept = verify_companies(client, "facts", "title", [_mention("A.NS"), _mention("B.NS")])

    assert [m.ticker for m in kept] == ["A.NS", "B.NS"]


def test_companies_without_a_ticker_are_never_judged_or_dropped():
    # Sector fan-out mentions have no ticker; they are not the verification
    # pass's business.
    tickerless = CompanyMention(
        name="fmcg sector", ticker=None, is_direct=False, sector="fmcg",
        direction="bullish", magnitude_low=1.0, magnitude_high=3.0,
        rationale="r", time_horizon="Short-Term",
    )
    client = _FakeClient({"verdicts": [{"ticker": "A.NS", "belongs": False}]})

    kept = verify_companies(client, "facts", "title", [_mention("A.NS"), tickerless])

    assert [m.name for m in kept] == ["fmcg sector"]


def test_no_call_is_made_for_an_empty_or_tickerless_list():
    client = _FakeClient({"verdicts": []})

    assert verify_companies(client, "facts", "title", []) == []
    assert client.calls == 0
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_verification.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.analysis.verification'`

- [ ] **Step 3: Implement**

```python
# backend/app/analysis/verification.py
"""Per-company verification: the explicit "does this company belong?" pass.

The cascade's own stages are generative -- each one is asked to FIND
companies, and a model asked to find things finds things. Nothing re-read the
assembled list and asked the opposite question, which is how a food-delivery
company survived to the card back of a crude-oil story.

This pass can only judge, never add: `ticker` is enum-constrained to the
already-assembled list, and any verdict naming a ticker outside it is
ignored. Failure keeps every company -- a provider outage must not silently
empty an alert, the same "degrade, never crash" discipline as
app.analysis.refinement.
"""
import json
import logging

from openai import RateLimitError

from app.analysis.claude_client import FALLBACK_MODEL, MODEL, SYSTEM_PROMPT
from app.analysis.schemas import CompanyMention

logger = logging.getLogger(__name__)

VERIFICATION_FRAMING = (
    "Below is a list of companies a previous analysis step proposed as "
    "affected by this news, each with the reason it gave. For EACH company, "
    "decide one thing only: does a specific, concrete mechanism from THESE "
    "facts genuinely reach THAT company's own business -- its revenue, its "
    "costs, its customers, or its competitive position?\n\n"
    "Set belongs=false when the link is thematic, generic, or true of the "
    "whole economy rather than this company; when the stated reason only "
    "says the company is large or well-known in a sector the news touches; "
    "or when the reason restates a fact from the article without connecting "
    "it to this company. Set belongs=true only when you could defend the "
    "link to a professional equity analyst reading the same article.\n\n"
    "Judge each company independently. Rejecting most of the list is a "
    "correct answer, and so is accepting all of it -- do not aim for a "
    "balance. You may not add companies; judge only what is listed."
)


def build_verification_tool(valid_tickers: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_company_verdicts",
            "description": "Judge whether each proposed company is genuinely affected by this news.",
            "parameters": {
                "type": "object",
                "properties": {
                    "verdicts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ticker": {"type": "string", "enum": valid_tickers},
                                "belongs": {"type": "boolean"},
                                "reason": {
                                    "type": "string",
                                    "description": "One line. Required when belongs is false.",
                                },
                            },
                            "required": ["ticker", "belongs"],
                        },
                    },
                },
                "required": ["verdicts"],
            },
        },
    }


def verify_companies(
    client, facts: str, title: str, companies: list[CompanyMention],
) -> list[CompanyMention]:
    """Returns the subset of `companies` that survives verification, in the
    original order.

    A company the model never returned a verdict for is KEPT -- omission is
    not a rejection (same discipline as
    app.analysis.refinement.generate_impact_whys). A company with no ticker
    (a sector fan-out mention) is never judged and always kept: it makes no
    company-specific claim to verify. Any failure returns the input list
    unchanged.
    """
    judgeable = [c for c in companies if c.ticker]
    if not judgeable:
        return companies

    tickers = [c.ticker for c in judgeable]
    listing = "\n".join(f"- {c.ticker} ({c.name}): {c.rationale}" for c in judgeable)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"{VERIFICATION_FRAMING}\n\nArticle: {title}\n\nFacts: {facts}\n\n"
            f"Proposed companies:\n{listing}"
        )},
    ]
    tool = build_verification_tool(tickers)

    def _call(model: str):
        return client.chat.completions.create(
            model=model, max_tokens=2048, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_company_verdicts"}},
            messages=messages,
        )

    try:
        try:
            response = _call(MODEL)
        except RateLimitError:
            response = _call(FALLBACK_MODEL)
        message = response.choices[0].message
        tool_call = next(
            (tc for tc in (message.tool_calls or []) if tc.function.name == "record_company_verdicts"),
            None,
        )
        if tool_call is None:
            logger.warning("verification returned no tool call; keeping every company")
            return companies
        arguments = json.loads(tool_call.function.arguments)
    except Exception as exc:
        logger.warning("verification call failed, keeping every company: %s", exc)
        return companies

    known = set(tickers)
    rejected: dict[str, str] = {}
    for verdict in arguments.get("verdicts", []):
        ticker = verdict.get("ticker")
        # Defensive: provider enums are not reliably enforced for nested
        # array items (cascade.py:282). A verdict about a company that is
        # not on the list cannot mean anything.
        if ticker not in known:
            continue
        if verdict.get("belongs") is False:
            rejected[ticker] = verdict.get("reason") or "no stated reason"

    for ticker, reason in rejected.items():
        logger.info("verification dropped %s: %s", ticker, reason)

    return [c for c in companies if not (c.ticker and c.ticker in rejected)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_verification.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Wire it into `analyze_article`**

In `backend/app/analysis/cascade.py`, add the import:

```python
from app.analysis.verification import verify_companies
```

In `analyze_article`, immediately before the `try:` that calls `_generate_edges`, insert:

```python
    # Verification (see app.analysis.verification): the only stage that asks
    # whether a company BELONGS rather than asking for more companies. Runs
    # once over the whole assembled list, after every generative stage and
    # before edges, so a dropped company never reaches the graph either.
    all_companies = verify_companies(client, facts_result.facts, title, all_companies)
```

- [ ] **Step 6: Write the wiring test**

Append to `backend/tests/test_cascade.py`:

```python
def test_analyze_article_drops_a_company_verification_rejects(monkeypatch):
    import app.analysis.cascade as cascade_module

    monkeypatch.setattr(
        cascade_module, "verify_companies",
        lambda client, facts, title, companies: [c for c in companies if c.ticker != "BAD.NS"],
    )
    # Build a client whose staged responses produce one good and one bad
    # company; reuse this module's existing multi-stage fake if present.
    ...
```

> Replace the `...` with a staged fake client matching whatever pattern `test_cascade.py` already uses for `analyze_article` (that file necessarily has one, since `analyze_article` makes several sequential calls). Assert that `BAD.NS` is absent from `result.companies` and the good ticker is present.

- [ ] **Step 7: Run the tests**

Run: `python -m pytest tests/test_cascade.py tests/test_verification.py -v`
Expected: PASS

- [ ] **Step 8: Run the full suite and commit**

Run: `python -m pytest`
Expected: PASS

```bash
git add backend/app/analysis/verification.py backend/app/analysis/cascade.py backend/tests/test_verification.py backend/tests/test_cascade.py
git commit -m "feat: per-company verification pass

Every cascade stage is generative -- asked to FIND companies, a model finds
companies. This is the first stage that asks the opposite question. Tickers
are enum-constrained to the assembled list so the pass can only judge, never
add; omission is not rejection; any failure keeps every company."
```

---

## Task 11: Constrain the sector fan-out

Spec Section 4. Keeps the fan-out (the exposure tier is intentional) but stops it from firing on narrow stories, from firing at cascade levels, and from reaching across unrelated sub-sectors.

**Files:**
- Modify: `backend/app/analysis/cascade.py`
- Modify: `backend/app/companies/resolution.py`
- Modify: `backend/tests/test_cascade.py`
- Modify: `backend/tests/test_resolution.py`

**Interfaces:**
- Consumes: `check_sub_sectors` data hygiene from Task 3.
- Produces:
  - `BROAD_EVENT_TYPES: frozenset[str]` in `app/analysis/cascade.py`
  - `_sector_fanout_mentions(sectors, impact_level, parent_ticker=None)` — unchanged signature
  - `TOP_N_SECTOR_COMPANIES = 3` in `app/companies/resolution.py`
  - `resolve_companies(session, mentions, anchor_sub_sectors: dict[str, set[str]] | None = None) -> list[dict]`

- [ ] **Step 1: Write the failing fan-out gating test**

Append to `backend/tests/test_cascade.py`:

```python
from app.analysis.cascade import BROAD_EVENT_TYPES


def test_broad_event_types_include_rate_and_commodity_moves():
    assert "repo_rate_change" in BROAD_EVENT_TYPES
    assert "crude_oil" in BROAD_EVENT_TYPES


def test_narrow_event_types_are_excluded():
    assert "earnings" not in BROAD_EVENT_TYPES
    assert "merger_acquisition" not in BROAD_EVENT_TYPES
    assert "order_win_contract" not in BROAD_EVENT_TYPES
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_cascade.py -k broad_event -v`
Expected: FAIL — `ImportError: cannot import name 'BROAD_EVENT_TYPES'`

- [ ] **Step 3: Add the event-type gate**

In `backend/app/analysis/cascade.py`, add above `_sector_fanout_mentions`:

```python
# Event types whose mechanism is genuinely broad enough that "every prominent
# company in this sector has some exposure" is a defensible claim -- a rate,
# commodity, currency, or trade/policy move really does reach costs, credit,
# or spending across a whole sector.
#
# Everything else is narrow: one company's earnings, one deal, one contract
# win. For those, sector-wide fan-out asserts an exposure that does not
# exist, which is most of what made alerts balloon to 35 companies. A narrow
# story's companies come from the analyzed stages alone.
BROAD_EVENT_TYPES = frozenset({
    "repo_rate_change", "inflation", "macro_data", "fiscal_policy",
    "monsoon_weather", "crude_oil", "commodity_price", "currency_move",
    "global_rates", "trade_policy",
})
```

- [ ] **Step 4: Gate the three fan-out call sites**

In `analyze_article`, replace:

```python
    all_companies.extend(_sector_fanout_mentions(primary_sectors, impact_level="direct"))
```

with:

```python
    # Fan-out only for genuinely broad events, and only at the primary level.
    # A cascade sector is already one hop from the news; fanning it out to
    # every prominent constituent stacks a generic claim on top of an
    # indirect one, which is where the worst noise came from (auto and
    # banking names on a crude-oil story via L1/L2 fan-out).
    fanout_allowed = facts_result.event_type in BROAD_EVENT_TYPES
    if fanout_allowed:
        all_companies.extend(_sector_fanout_mentions(primary_sectors, impact_level="direct"))
```

Then delete both cascade fan-out blocks entirely. Remove:

```python
        if l1_sectors:
            all_companies.extend(_sector_fanout_mentions(
                l1_sectors, impact_level="indirect_l1", parent_ticker=l1_parent_tickers_present[0].ticker,
            ))
```

and:

```python
            if l2_sectors:
                all_companies.extend(_sector_fanout_mentions(
                    l2_sectors, impact_level="indirect_l2", parent_ticker=l2_parent_tickers_present[0].ticker,
                ))
```

- [ ] **Step 5: Write the failing sub-sector anchoring test**

Append to `backend/tests/test_resolution.py`:

```python
def test_fanout_prefers_companies_sharing_a_named_company_sub_sector(db_session):
    db_session.add_all([
        Company(ticker="ITC.NS", name="ITC Ltd.", sector="fmcg",
                sub_sector="staples_food", index_tier="NIFTY50"),
        Company(ticker="ETERNAL.NS", name="Eternal Ltd.", sector="fmcg",
                sub_sector="retail", index_tier="NIFTY50"),
        Company(ticker="NESTLEIND.NS", name="Nestle India Ltd.", sector="fmcg",
                sub_sector="staples_food", index_tier="NIFTY50"),
    ])
    db_session.commit()

    resolved = resolve_companies(
        db_session,
        [CompanyMention(
            name="fmcg sector", is_direct=False, sector="fmcg",
            direction="bullish", magnitude_low=1.0, magnitude_high=3.0,
            rationale="r", time_horizon="Short-Term",
        )],
        anchor_sub_sectors={"fmcg": {"staples_food"}},
    )

    tickers = {r["company_id"] for r in resolved}
    names = {
        db_session.query(Company).get(cid).ticker for cid in tickers
    }
    assert names == {"ITC.NS", "NESTLEIND.NS"}


def test_fanout_without_an_anchor_falls_back_to_the_whole_sector(db_session):
    db_session.add_all([
        Company(ticker="ITC.NS", name="ITC Ltd.", sector="fmcg",
                sub_sector="staples_food", index_tier="NIFTY50"),
        Company(ticker="ETERNAL.NS", name="Eternal Ltd.", sector="fmcg",
                sub_sector="retail", index_tier="NIFTY50"),
    ])
    db_session.commit()

    resolved = resolve_companies(db_session, [CompanyMention(
        name="fmcg sector", is_direct=False, sector="fmcg",
        direction="bullish", magnitude_low=1.0, magnitude_high=3.0,
        rationale="r", time_horizon="Short-Term",
    )])

    assert len(resolved) == 2


def test_top_n_sector_companies_is_three():
    from app.companies.resolution import TOP_N_SECTOR_COMPANIES
    assert TOP_N_SECTOR_COMPANIES == 3
```

- [ ] **Step 6: Run it to make sure it fails**

Run: `python -m pytest tests/test_resolution.py -k "anchor or top_n" -v`
Expected: FAIL — `resolve_companies() got an unexpected keyword argument 'anchor_sub_sectors'`

- [ ] **Step 7: Implement anchoring and the new limit**

In `backend/app/companies/resolution.py`, change the constant:

```python
# Lowered from 5. Fan-out is an exposure tier, not an analysis tier -- three
# prominent constituents convey "this sector has exposure" as well as five
# do, at 40% less noise.
TOP_N_SECTOR_COMPANIES = 3
```

Change the signature and docstring addition:

```python
def resolve_companies(
    session: Session, mentions: list[CompanyMention],
    anchor_sub_sectors: dict[str, set[str]] | None = None,
) -> list[dict]:
```

Add to the docstring, before the closing quotes:

```
    anchor_sub_sectors: {sector: {sub_sector, ...}} built from the companies
    the model NAMED for each sector. When present, a sector's fan-out is
    restricted to companies sharing one of those sub-sectors, so a crude-oil
    story reaching "fmcg" pulls staples_food (where the named companies are)
    rather than every prominent fmcg name regardless of what it sells. Falls
    back to the whole sector when a sector has no anchor -- an unanchored
    sector still deserves its exposure tier, just a less targeted one.
```

Replace the fan-out query in the `else:` branch:

```python
            query = (
                session.query(Company)
                .filter_by(sector=mention.sector)
                .filter(Company.ticker.notin_(DEMO_TICKERS))
            )
            anchors = (anchor_sub_sectors or {}).get(mention.sector)
            if anchors:
                query = query.filter(Company.sub_sector.in_(anchors))
            companies = (
                query.order_by(_TIER_RANK.asc(), Company.ticker.asc())
                .limit(TOP_N_SECTOR_COMPANIES)
                .all()
            )
```

- [ ] **Step 8: Build the anchor map in the pipeline**

In `backend/app/pipeline.py::process_new_articles`, replace:

```python
        resolved = resolve_companies(session, analysis.companies)
```

with:

```python
        # Anchor each sector's fan-out to the sub-sectors of the companies
        # the model actually named there -- see resolve_companies.
        anchor_sub_sectors: dict[str, set[str]] = {}
        for mention in analysis.companies:
            if not (mention.is_direct and mention.ticker and mention.sector):
                continue
            company = session.query(Company).filter_by(ticker=mention.ticker).one_or_none()
            if company is not None and company.sub_sector:
                anchor_sub_sectors.setdefault(mention.sector, set()).add(company.sub_sector)

        resolved = resolve_companies(session, analysis.companies, anchor_sub_sectors=anchor_sub_sectors)
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `python -m pytest tests/test_resolution.py tests/test_cascade.py tests/test_pipeline.py -v`
Expected: PASS

> Existing tests that assert 5 fan-out companies will now see 3. Update those assertions — the change is intentional and the spec records it.

- [ ] **Step 10: Run the full suite and commit**

Run: `python -m pytest`
Expected: PASS

```bash
git add backend/app/analysis/cascade.py backend/app/companies/resolution.py backend/tests/test_cascade.py backend/tests/test_resolution.py backend/tests/test_pipeline.py
git commit -m "fix: constrain sector fan-out to broad events, primary level, anchored sub-sectors

Three limits on the exposure tier. Only BROAD_EVENT_TYPES fan out at all -- a
single company's earnings does not give a whole sector exposure. Cascade
levels no longer fan out, which is where the auto and banking names on a
crude-oil story came from. And a sector's fan-out is restricted to the
sub-sectors of the companies the model actually named there. TOP_N 5 -> 3."
```

---

## Task 12: Model routing and temperature

Spec Section 6. `_GeminiCompletions.create` swallows the `model` kwarg via `**_ignored`, so `MODEL` vs `FALLBACK_MODEL` throughout `cascade.py` is dead code and every stage runs on `gemini-flash-latest`. `temperature` is never set, so Gemini defaults to 1.0 on an extraction task.

**Files:**
- Modify: `backend/app/analysis/claude_client.py`
- Modify: `backend/tests/test_claude_client.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `GEMINI_STRONG_MODEL: str`
  - `ANALYSIS_TEMPERATURE: float`
  - `GeminiAdapter(api_key, model=GEMINI_MODEL, strong_model=GEMINI_STRONG_MODEL)`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_claude_client.py`:

```python
from app.analysis.claude_client import (
    ANALYSIS_TEMPERATURE, GEMINI_MODEL, GEMINI_STRONG_MODEL, GeminiAdapter,
)


def test_gemini_maps_the_strong_model_slot_to_the_strong_model(monkeypatch):
    captured = {}

    def _fake_post(url, json, timeout):
        captured["url"] = url
        captured["body"] = json
        return SimpleNamespace(status_code=200, json=lambda: {"candidates": []})

    monkeypatch.setattr("app.analysis.claude_client.httpx.post", _fake_post)

    adapter = GeminiAdapter("key")
    adapter.chat.completions.create(
        model=MODEL, max_tokens=100, tools=[_tool()],
        messages=[{"role": "user", "content": "hi"}],
    )

    assert GEMINI_STRONG_MODEL in captured["url"]


def test_gemini_maps_the_fallback_model_slot_to_the_cheap_model(monkeypatch):
    captured = {}

    def _fake_post(url, json, timeout):
        captured["url"] = url
        return SimpleNamespace(status_code=200, json=lambda: {"candidates": []})

    monkeypatch.setattr("app.analysis.claude_client.httpx.post", _fake_post)

    adapter = GeminiAdapter("key")
    adapter.chat.completions.create(
        model=FALLBACK_MODEL, max_tokens=100, tools=[_tool()],
        messages=[{"role": "user", "content": "hi"}],
    )

    assert GEMINI_MODEL in captured["url"]


def test_gemini_sets_a_low_temperature(monkeypatch):
    captured = {}

    def _fake_post(url, json, timeout):
        captured["body"] = json
        return SimpleNamespace(status_code=200, json=lambda: {"candidates": []})

    monkeypatch.setattr("app.analysis.claude_client.httpx.post", _fake_post)

    GeminiAdapter("key").chat.completions.create(
        model=MODEL, max_tokens=100, tools=[_tool()],
        messages=[{"role": "user", "content": "hi"}],
    )

    assert captured["body"]["generationConfig"]["temperature"] == ANALYSIS_TEMPERATURE
    assert ANALYSIS_TEMPERATURE <= 0.3


def _tool():
    return {"type": "function", "function": {
        "name": "t", "description": "d",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }}
```

> Add `from types import SimpleNamespace` and the `MODEL` / `FALLBACK_MODEL` imports at the top of the test file if not already present.

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_claude_client.py -k gemini -v`
Expected: FAIL — `ImportError: cannot import name 'GEMINI_STRONG_MODEL'`

- [ ] **Step 3: Implement**

In `backend/app/analysis/claude_client.py`, add below `GEMINI_MODEL`:

```python
# The stage-quality slot. cascade.py already distinguishes its hardest calls
# (company identification, which passes MODEL) from its cheaper ones (facts,
# sectors, edge verification, which pass FALLBACK_MODEL) -- but
# _GeminiCompletions discarded the model kwarg entirely via **_ignored, so
# every stage silently ran on GEMINI_MODEL and that distinction was dead
# code. Honoring it makes the paid migration a one-line change here rather
# than a pipeline rewrite: point this at a stronger model and the hard
# stages upgrade on their own.
#
# Today both slots resolve to the same free flash model, so this is a no-op
# in behavior and a real change in structure.
GEMINI_STRONG_MODEL = "gemini-flash-latest"

# Company/sector identification is extraction, not brainstorming. Gemini
# defaults to 1.0 when unset, which is the wrong end of the range for a task
# whose output must be reproducible enough to regression-test.
ANALYSIS_TEMPERATURE = 0.2
```

Replace `_GeminiCompletions` `__init__` and `create`:

```python
    def __init__(self, api_key: str, model: str = GEMINI_MODEL, strong_model: str = GEMINI_STRONG_MODEL):
        self._api_key = api_key
        self._model = model
        self._strong_model = strong_model

    def _resolve_model(self, requested: str | None) -> str:
        """Callers pass Groq model names (MODEL for the hard stages,
        FALLBACK_MODEL for the cheap ones). Map that intent onto this
        provider's own two slots rather than discarding it."""
        if requested == MODEL:
            return self._strong_model
        return self._model

    def create(self, *, max_tokens, tools, messages, model=None, **_ignored):
        system_content = None
        contents = []
        for m in messages:
            if m["role"] == "system":
                system_content = m["content"]
            else:
                contents.append({"role": "user", "parts": [{"text": m["content"]}]})

        function_spec = tools[0]["function"]
        function_declaration = {
            "name": function_spec["name"],
            "description": function_spec["description"],
            "parameters": _uppercase_schema_types(function_spec["parameters"]),
        }

        body = {
            "contents": contents,
            "tools": [{"function_declarations": [function_declaration]}],
            "tool_config": {"function_calling_config": {"mode": "ANY"}},
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": ANALYSIS_TEMPERATURE,
            },
        }
        if system_content is not None:
            body["systemInstruction"] = {"parts": [{"text": system_content}]}

        resolved_model = self._resolve_model(model)
        url = f"{GEMINI_BASE_URL}/models/{resolved_model}:generateContent?key={self._api_key}"
```

> The rest of `create` (the `httpx.post` call onward) is unchanged. `MODEL` is defined below `GEMINI_STRONG_MODEL` in the current file — move the `MODEL` / `FALLBACK_MODEL` block above the Gemini block so `_resolve_model` can reference it, or reference it lazily inside the method.

Update `_GeminiChat` and `GeminiAdapter` to thread `strong_model`:

```python
class _GeminiChat:
    def __init__(self, api_key: str, model: str, strong_model: str):
        self.completions = _GeminiCompletions(api_key, model, strong_model)


class GeminiAdapter:
    """Duck-types the OpenAI client surface analyze_article uses, backed by
    a raw Gemini generateContent REST call, so the rest of the pipeline
    never needs to know which provider actually served a given call.
    Honors the caller's model slot (see _GeminiCompletions._resolve_model)."""

    def __init__(
        self, api_key: str, model: str = GEMINI_MODEL, strong_model: str = GEMINI_STRONG_MODEL,
    ):
        self.chat = _GeminiChat(api_key, model, strong_model)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_claude_client.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest`
Expected: PASS

```bash
git add backend/app/analysis/claude_client.py backend/tests/test_claude_client.py
git commit -m "fix: Gemini adapter honors the model slot and pins a low temperature

_GeminiCompletions discarded the model kwarg via **_ignored, so cascade.py's
MODEL vs FALLBACK_MODEL distinction was dead code and every stage ran on the
cheap flash model. Maps the two slots onto GEMINI_STRONG_MODEL /
GEMINI_MODEL -- both flash today, so behavior is unchanged, but the paid
migration becomes a one-line change. temperature 0.2: this is extraction, and
Gemini defaults to 1.0 when unset."
```

---

## Task 13: Direction/rationale coherence

Spec Section 7. `_persist_alert` overwrites `direction` from the measured market move but leaves `rationale` untouched, producing a bullish badge above bearish prose.

**Files:**
- Modify: `backend/app/pipeline.py`
- Modify: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: no new symbols.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_pipeline.py`:

```python
def test_a_flipped_direction_clears_the_stale_rationale(db_session, monkeypatch):
    # The LLM called bullish; the measured move came back negative. The
    # rationale argues the bullish case and must not survive under a bearish
    # badge.
    article = _article(db_session)
    company = Company(ticker="X.NS", name="X Ltd.", sector="other")
    db_session.add(company)
    db_session.commit()

    _stub_measurement(monkeypatch, excess_move_pct=-3.1)

    alert = _persist_alert(db_session, article, "other", [{
        "company_id": company.id, "direction": "bullish",
        "magnitude_low": 1.0, "magnitude_high": 2.0,
        "rationale": "This is clearly good news for the company.",
        "key_points": ["good news"], "basis": "direct_mention",
        "time_horizon": "Short-Term", "impact_level": "direct",
    }])

    ac = alert.companies[0]
    assert ac.direction == "bearish"
    assert ac.rationale is None
    assert decode_key_points(ac) == []


def test_a_confirmed_direction_keeps_its_rationale(db_session, monkeypatch):
    article = _article(db_session)
    company = Company(ticker="X.NS", name="X Ltd.", sector="other")
    db_session.add(company)
    db_session.commit()

    _stub_measurement(monkeypatch, excess_move_pct=2.4)

    alert = _persist_alert(db_session, article, "other", [{
        "company_id": company.id, "direction": "bullish",
        "magnitude_low": 1.0, "magnitude_high": 2.0,
        "rationale": "This is clearly good news for the company.",
        "key_points": ["good news"], "basis": "direct_mention",
        "time_horizon": "Short-Term", "impact_level": "direct",
    }])

    assert alert.companies[0].rationale == "This is clearly good news for the company."
```

> `_stub_measurement` monkeypatches `app.pipeline.measure_company_move` to return a `MarketMove` with `measurement_status="ok"` and the given `excess_move_pct`. Reuse `test_market_move_wiring.py`'s approach if it already has one.

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_pipeline.py -k stale_rationale -v`
Expected: FAIL — rationale still contains the bullish text

- [ ] **Step 3: Implement**

In `backend/app/pipeline.py`, replace the direction-reconciliation loop:

```python
    moves_by_company_id = {m.company_id: m for m in market_moves}
    for alert_company in alert_companies:
        move = moves_by_company_id.get(alert_company.company_id)
        if move is not None and move.measurement_status == "ok" and move.excess_move_pct is not None:
            alert_company.direction = "bullish" if move.excess_move_pct >= 0 else "bearish"
```

with:

```python
    moves_by_company_id = {m.company_id: m for m in market_moves}
    for alert_company in alert_companies:
        move = moves_by_company_id.get(alert_company.company_id)
        if move is None or move.measurement_status != "ok" or move.excess_move_pct is None:
            continue
        measured_direction = "bullish" if move.excess_move_pct >= 0 else "bearish"
        if measured_direction != alert_company.direction:
            # The rationale and key_points argue for the direction the LLM
            # predicted, which the measured reaction has just contradicted.
            # Leaving them produces a bearish badge above bullish prose for
            # the same company. Drop the text rather than keep an argument
            # for a call that no longer stands -- refine_alert generates a
            # fresh, measurement-aware `why` for this company below.
            alert_company.rationale = None
            alert_company.key_points_json = json.dumps([])
        alert_company.direction = measured_direction
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite and commit**

Run: `python -m pytest`
Expected: PASS

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "fix: clear stale rationale when measurement flips the direction

The LLM's direction is a prediction made before the market reacted, and
measurement overwrites it -- but rationale and key_points still argued the
original call, so a bearish badge could sit above bullish prose. Clear the
text on a flip; refine_alert's measurement-aware why replaces it."
```

---

## Task 14: Repair tier-1 ripple layers

Spec Section 8. `alert_ripple_layers` has zero rows across all 607 alerts. `refine_alert`'s other three outputs populated on the same alerts (12 summaries, 13 timeline effects, 14 whys), so the client and call path work — the failure is inside `generate_ripple_layers`.

**Files:**
- Modify: `backend/app/analysis/refinement.py`
- Modify: `backend/tests/test_refinement.py`

**Interfaces:**
- Consumes: Task 5's `direct_mention`-only company list.
- Produces: no new symbols. `generate_ripple_layers` gains diagnostic logging and whatever fix the diagnosis indicates.

- [ ] **Step 1: Add diagnostic logging first**

The current code degrades silently to `[]`, so a total failure is indistinguishable from "no sections applied". In `backend/app/analysis/refinement.py`, add at the top:

```python
import logging

logger = logging.getLogger(__name__)
```

Then in `generate_ripple_layers`, replace the final `except Exception:` and the `tool_call is None` branch:

```python
        if tool_call is None:
            logger.warning(
                "ripple-layer generation returned no tool call for %d companies", len(companies),
            )
            return []
```

and, inside the validation loop, log each rejection. Replace the loop body:

```python
        for layer in arguments.get("layers", []):
            if layer.get("relationship") not in RIPPLE_RELATIONSHIP_TYPES:
                logger.warning("ripple layer rejected: bad relationship %r", layer.get("relationship"))
                continue
            layer_title = validate_or_none(layer.get("title"))
            note = validate_or_none(layer.get("note"))
            if not layer_title or not note:
                logger.warning(
                    "ripple layer rejected by compliance: title=%r note=%r",
                    layer.get("title"), layer.get("note"),
                )
                continue
            tickers = [
                t for t in layer.get("tickers", [])
                if t in known_tickers and t not in seen
            ]
            if not tickers:
                logger.warning(
                    "ripple layer %r rejected: no known unclaimed tickers in %r",
                    layer_title, layer.get("tickers"),
                )
                continue
            seen.update(tickers)
            validated.append({
                "title": layer_title, "relationship": layer["relationship"],
                "note": note, "tickers": tickers,
            })
        if not validated:
            logger.warning("ripple-layer generation produced no valid layers from %d raw layers",
                           len(arguments.get("layers", [])))
        return validated
    except Exception as exc:
        logger.warning("ripple-layer generation failed: %s", exc)
        return []
```

- [ ] **Step 2: Reproduce against a live alert**

```bash
python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
from app.config import settings
from app.analysis.claude_client import build_client
from app.analysis.refinement import generate_ripple_layers
from app.db import SessionLocal
from app.models import Alert, Company

s = SessionLocal()
alert = s.query(Alert).filter_by(id=9020).one()
companies = []
for ac in alert.companies:
    if ac.basis == 'sector_inference':
        continue
    c = s.get(Company, ac.company_id)
    companies.append({'ticker': c.ticker, 'name': c.name, 'sector': c.sector,
                      'sub_sector': c.sub_sector, 'direction': ac.direction, 'why': ac.why})
client = build_client(settings.groq_api_key, settings.gemini_api_key)
print('INPUT:', companies)
print('OUTPUT:', generate_ripple_layers(client, alert.article.title, alert.article.content, companies))
s.close()
"
```

> Check `app/config.py` for the real settings attribute names for the Groq and Gemini keys, and use those.

Read the logged warnings. They identify which of the three candidate causes fired.

- [ ] **Step 3: Apply the fix the diagnosis indicates**

Match the fix to what Step 2 actually showed:

**If "returned no tool call"** — the nested schema or token budget starved the response, the failure mode documented in `cascade.py::_identify_cascade_companies_per_sector`. Raise `max_tokens` from 1536 to 4096 in `generate_ripple_layers`'s `_call`.

**If "rejected by compliance"** — a title or note tripped `validate_no_advice_language`. The most likely trigger is `_ADVICE_WORDS_RE` matching a word like `holds` or `buy` inside otherwise-fine copy. Add an instruction to `RIPPLE_LAYERS_FRAMING` forbidding those words explicitly:

```python
    "Never use the words buy, sell, hold, or any rating or price-target "
    "language in a title or note -- such a section is discarded entirely."
```

**If "bad relationship"** — the model returned a value outside `RIPPLE_RELATIONSHIP_TYPES`. The enum is already in the tool schema, so this is the nested-array enforcement gap; log the offending value and consider mapping obvious near-misses (e.g. `"DIRECT_IMPACT"` → `"DIRECT"`) rather than discarding.

**If "no known unclaimed tickers"** — the model returned tickers not in the supplied set. Verify the company list passed in is non-empty after Task 5's `direct_mention` filter; if an alert has only fan-out rows, an empty result is correct and not a bug.

- [ ] **Step 4: Write a regression test**

Append to `backend/tests/test_refinement.py`, matching that file's existing fake-client pattern:

```python
def test_generate_ripple_layers_returns_a_validated_layer():
    client = _fake_client_returning("record_ripple_layers", {"layers": [{
        "title": "Losers — refiners",
        "relationship": "DIRECT",
        "note": "Crude costs rise faster than pump prices can follow.",
        "tickers": ["HPCL.NS", "BPCL.NS"],
    }]})

    layers = generate_ripple_layers(client, "title", "content", [
        {"ticker": "HPCL.NS", "name": "HPCL", "sector": "oil_gas",
         "sub_sector": "refining_marketing", "direction": "bearish", "why": None},
        {"ticker": "BPCL.NS", "name": "BPCL", "sector": "oil_gas",
         "sub_sector": "refining_marketing", "direction": "bearish", "why": None},
    ])

    assert len(layers) == 1
    assert layers[0]["tickers"] == ["HPCL.NS", "BPCL.NS"]
    assert layers[0]["relationship"] == "DIRECT"


def test_generate_ripple_layers_logs_and_returns_empty_on_no_tool_call(caplog):
    client = _fake_client_returning("record_ripple_layers", None)

    layers = generate_ripple_layers(client, "title", "content", [
        {"ticker": "HPCL.NS", "name": "HPCL", "sector": "oil_gas",
         "sub_sector": "refining_marketing", "direction": "bearish", "why": None},
    ])

    assert layers == []
    assert "no tool call" in caplog.text
```

> `_fake_client_returning(tool_name, payload)` returns a client whose `create` yields that tool call, or no tool calls when `payload` is `None`. Reuse `test_refinement.py`'s existing helper if it has one.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_refinement.py tests/test_generated_ripple_layers.py -v`
Expected: PASS

- [ ] **Step 6: Verify live**

Re-run the Step 2 command.
Expected: a non-empty list of layers.

- [ ] **Step 7: Run the full suite and commit**

Run: `python -m pytest`
Expected: PASS

```bash
git add backend/app/analysis/refinement.py backend/tests/test_refinement.py
git commit -m "fix: restore tier-1 story-adaptive ripple layers

alert_ripple_layers had zero rows across all 607 alerts -- the top tier of
the card-back sectioning had never produced a section. refine_alert's other
outputs populated on the same alerts, localizing the failure to
generate_ripple_layers itself. Adds rejection logging at every discard point
so a total failure can no longer look like 'no sections applied'."
```

---

## Task 15: Migrate existing alerts

Spec Section 10, first half. Zero API calls, minutes to run, fixes the presentation of all 607 alerts.

**Files:**
- Create: `backend/migrate_precision.py`

**Interfaces:**
- Consumes: `CONFIDENCE_FLOOR` from Task 6, `DEMO_TICKERS` from Task 2.
- Produces: no new symbols.

- [ ] **Step 1: Write the migration script**

```python
# backend/migrate_precision.py
"""One-off migration bringing existing alerts in line with the precision
fixes (docs/superpowers/specs/2026-08-03-impact-analysis-precision-design.md
Section 10). Zero LLM calls.

Three changes, all to already-persisted AlertCompany rows:
1. Clear the template rationale on every sector_inference row -- it reads as
   per-company analysis but was built from the sector's one-line mechanism.
2. Drop rows below CONFIDENCE_FLOOR.
3. Drop rows pointing at a demo company that no longer exists.

Bucket routing needs no migration: app.market.ripple_layers dispatches on
basis at READ time, so every existing sector_inference row moves to
SECTOR_WIDE the moment Task 4 ships.

Idempotent: re-running changes nothing further. Pass --dry-run to see counts
without writing.
"""
import argparse

from app.companies.integrity import DEMO_TICKERS
from app.db import SessionLocal
from app.models import AlertCompany, Company
from app.pipeline import CONFIDENCE_FLOOR


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        template_rows = (
            session.query(AlertCompany)
            .filter(AlertCompany.basis == "sector_inference")
            .filter(AlertCompany.rationale.isnot(None))
            .all()
        )
        low_rows = (
            session.query(AlertCompany)
            .filter(AlertCompany.confidence_score < CONFIDENCE_FLOOR)
            .all()
        )
        demo_company_ids = [
            c.id for c in session.query(Company).filter(Company.ticker.in_(DEMO_TICKERS)).all()
        ]
        demo_rows = (
            session.query(AlertCompany)
            .filter(AlertCompany.company_id.in_(demo_company_ids))
            .all()
        ) if demo_company_ids else []

        print(f"sector_inference rows with a template rationale: {len(template_rows)}")
        print(f"rows below confidence floor {CONFIDENCE_FLOOR}:         {len(low_rows)}")
        print(f"rows pointing at a demo company:                  {len(demo_rows)}")

        if args.dry_run:
            print("\n--dry-run: nothing written.")
            return

        for row in template_rows:
            row.rationale = None
            row.key_points_json = "[]"
        # Delete after the rationale pass so a row that is both gets counted
        # in both totals above but deleted once.
        for row in {id(r): r for r in (low_rows + demo_rows)}.values():
            session.delete(row)
        session.commit()
        print("\nDone.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run it**

Run: `python migrate_precision.py --dry-run`
Expected: roughly 557 template rationales, ~20 below-floor rows, and demo rows only if Task 2's deletion has not run yet.

- [ ] **Step 3: Back up the database**

```bash
cp newsflo.db newsflo.db.pre-precision-migration
```

> Production runs Postgres. Take whatever backup that environment uses before running this there.

- [ ] **Step 4: Run the migration**

Run: `python migrate_precision.py`
Expected: `Done.`

- [ ] **Step 5: Verify idempotence**

Run: `python migrate_precision.py --dry-run`
Expected: all three counts are 0

- [ ] **Step 6: Spot-check the reported alert**

```bash
python -c "
from app.db import SessionLocal
from app.models import Alert, Company
s = SessionLocal()
a = s.query(Alert).filter_by(id=9020).one()
for ac in sorted(a.companies, key=lambda x: x.basis):
    c = s.get(Company, ac.company_id)
    print(f'{ac.basis:18} {c.ticker:16} rationale={ac.rationale is not None}')
s.close()
"
```
Expected: every `sector_inference` row shows `rationale=False`; `direct_mention` rows show `rationale=True`.

- [ ] **Step 7: Commit**

```bash
git add backend/migrate_precision.py
git commit -m "chore: migration bringing existing alerts in line with the precision fixes

Clears template rationales on sector_inference rows, drops sub-floor rows and
rows pointing at deleted demo companies. Bucket routing needs no migration --
ripple_layers dispatches on basis at read time. Idempotent, --dry-run
supported, zero LLM calls."
```

---

## Task 16: Reanalyze the recent window and score the result

Spec Section 10, second half, plus the Section 0 measurement that closes the loop.

**Files:**
- Modify: `backend/reanalyze_cascade.py` (only if it lacks a date-window argument)
- Create: `backend/score_golden.py`

**Interfaces:**
- Consumes: `GOLDEN_CASES`, `score_all` from Task 1.
- Produces: no new importable symbols; `score_golden.py` is a CLI.

- [ ] **Step 1: Write the scorer CLI**

```python
# backend/score_golden.py
"""Scores the CURRENT contents of the database against the golden set.

Reads what each golden alert actually has persisted rather than re-running
analysis, so it is cheap, repeatable, and safe to run after every task. Run
it before and after a change to see what moved.
"""
import sys

sys.path.insert(0, "tests")

from app.db import SessionLocal
from app.models import Alert, Company
from tests.golden.cases import GOLDEN_CASES
from tests.golden.score import score_all


def main() -> None:
    session = SessionLocal()
    try:
        results = {}
        for case in GOLDEN_CASES:
            alert = session.query(Alert).filter_by(id=case.alert_id).one_or_none()
            if alert is None:
                print(f"WARNING: golden alert {case.alert_id} not in this database")
                continue
            results[case.alert_id] = {
                session.get(Company, ac.company_id).ticker for ac in alert.companies
            }

        run = score_all(results)
        for case_score in run.cases:
            status = "OK " if not case_score.forbidden and not case_score.missing else "FAIL"
            print(f"[{status}] alert {case_score.alert_id}  "
                  f"precision={case_score.precision:.2f} recall={case_score.recall:.2f}")
            if case_score.forbidden:
                print(f"         MUST NOT be present: {sorted(case_score.forbidden)}")
            if case_score.missing:
                print(f"         MISSING:            {sorted(case_score.missing)}")

        print(f"\nmean precision {run.mean_precision:.2f}   "
              f"mean recall {run.mean_recall:.2f}   "
              f"forbidden companies present: {run.total_forbidden}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Record the baseline**

Run: `python score_golden.py`

Write the numbers down. This is the "before" figure for alert 9020 — with the migration applied but no reanalysis yet, forbidden companies should still be present because the fan-out rows are still persisted (they moved buckets, they did not disappear).

- [ ] **Step 3: Check the reanalysis script's window support**

Run: `cat reanalyze_cascade.py`

Confirm it can be limited to a date window and that it clears the analysis cache (`clear_analysis_cache`) — otherwise `get_cached_analysis` returns the old, pre-fix result and nothing changes. If either is missing, add a `--days N` argument and force cache clearing.

- [ ] **Step 4: Reanalyze the last 7 days**

Run: `python reanalyze_cascade.py --days 7 --force`

> Use whatever the script's actual flags are. Expect this to be slow on free-tier quotas.

- [ ] **Step 5: Score again**

Run: `python score_golden.py`
Expected: `forbidden companies present: 0` for alert 9020 — `ETERNAL.NS` and the L1/L2 fan-out names gone, `HPCL.NS` / `BPCL.NS` / `INDIGO.NS` / `ASIANPAINT.NS` still present.

If forbidden companies remain, do not paper over it — identify which stage reintroduced them:
- Still `sector_inference`? Task 11's gating did not fire. Check the alert's `event_type` against `BROAD_EVENT_TYPES`, and check `anchor_sub_sectors` was built.
- Now `direct_mention`? Grounding or verification let it through. Check whether the company was in the candidate list, and whether `verify_companies` was reached.

- [ ] **Step 6: Commit**

```bash
git add backend/score_golden.py backend/reanalyze_cascade.py
git commit -m "feat: golden-set scorer CLI and 7-day reanalysis window

score_golden.py reads what each golden alert actually has persisted rather
than re-running analysis, so it is cheap enough to run after every change.
Reanalysis must clear the analysis cache or get_cached_analysis returns the
pre-fix result."
```

- [ ] **Step 7: Record the final numbers in the spec**

Append a short "Results" section to `docs/superpowers/specs/2026-08-03-impact-analysis-precision-design.md` with the before/after `score_golden.py` output, then commit.

```bash
git add docs/superpowers/specs/2026-08-03-impact-analysis-precision-design.md
git commit -m "docs: record measured before/after for the precision work"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| 0 — Evaluation harness | 1, 16 |
| 1 — Stop the bleed | 4, 5, 6 |
| 2 — Grounding | 7, 8, 9 |
| 3 — Verification pass | 10 |
| 4 — Fan-out repair | 11 |
| 5 — Taxonomy repair | 3 (deterministic), 9 (descriptions), 3 Step 6 (NIFTY50 review) |
| 6 — Model routing | 12 |
| 7 — Coherence | 13 |
| 8 — Tier-1 repair | 14 |
| 9 — Demo data purge | 2 |
| 10 — Migration | 15, 16 |
| Success criterion 1 (zero must-exclude) | 16 Step 5 |
| Success criterion 2 (fewer empty alerts) | 8, 9 — measured in 16 |
| Success criterion 3 (no fan-out in DIRECT) | 4, 5 |
| Success criterion 4 (ripple layers populated) | 14 |

No spec section is unimplemented.

**Known judgement calls, flagged rather than hidden:**

- Task 3 Step 6 and Task 9 Step 5 require human review of company data. Neither can be fully automated — the taxonomy calls are judgement, and `ETERNAL.NS` is the specific known-wrong row.
- Task 14 Step 3 branches on a diagnosis that cannot be made until the reproduction in Step 2 runs. All four branches are specified with concrete fixes; which one applies is genuinely unknown until then.
- Task 1's `GOLDEN_CASES` ships with one case. Thirty is the target, and adding them needs the human's labels.

**Type consistency:** `resolve_companies(session, mentions, anchor_sub_sectors=None)` is defined in Task 11 and called with that keyword in Task 11 Step 8. `_identify_companies(..., session=None)` is defined in Task 8 and called with `session=` in Tasks 8 Step 6 and 10. `build_company_tool(parent_tickers, valid_tickers=None)` is defined and called consistently in Task 8. `verify_companies(client, facts, title, companies)` is defined in Task 10 and called with four positional arguments in Task 10 Step 5 and monkeypatched with the same signature in Step 6. `CONFIDENCE_FLOOR` is defined in Task 6 and imported in Tasks 6 and 15. `DEMO_TICKERS` is defined in Task 2 and imported in Tasks 2, 7, and 15.
