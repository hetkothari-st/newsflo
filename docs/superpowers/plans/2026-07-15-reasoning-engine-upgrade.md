# Reasoning Engine Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace LLM-self-rated confidence with a deterministic Confidence Engine, inject a domain reasoning rulebook + sector playbooks into the analysis prompt, and add evidence-per-claim discipline (reasons/risks/assumptions/unknowns/evidence_refs) to every company impact — all wired to the existing outcome-calibration flywheel (`app/outcomes/tracker.py` + `app/calibration/blender.py`, both already running in production).

**Architecture:** Extends the existing single-call FastAPI/SQLAlchemy pipeline in place. No new services, no second LLM call, no new datastore. Domain knowledge (rulebook + playbooks) ships as static Python data always injected into the existing `ANALYSIS_INSTRUCTIONS` prompt (same mechanism `SECTOR_DEFINITIONS` already uses) — not a per-article classification/selection step, since the content is compact enough that always-on beats building selection infrastructure. A new `app/reasoning/` package holds the rulebook, playbooks, and confidence-scoring logic as small, independently-testable pure-function modules.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy (SQLite dev / Postgres prod, no Alembic — manual `_ADDED_COLUMNS` migration in `app/db.py`), pytest, Pydantic v2.

## Deviation from the design spec

`docs/superpowers/specs/2026-07-15-reasoning-engine-upgrade-design.md` proposed splitting analysis into two sequential LLM calls (Call A: event classification → Call B: reasoning informed by a rulebook excerpt selected by Call A's output). This plan implements it as **one call**, for two reasons discovered during planning:

1. **Chicken-and-egg on sector selection.** The design's "inject the playbook excerpt selected by sector" doesn't work before the call completes — sector is a per-company output of the very call the excerpt would be injected into. The actual fix (inject *all* playbooks, since they're short) removes the need for per-article selection at all, which removes the need for a first classification call.
2. **Test/latency/cost cost with no offsetting benefit.** A second call adds latency, cost, and — critically — breaks every existing test in `test_pipeline.py` that monkeypatches `pipeline_module.analyze_article` (each would need a second monkeypatch target). Since the rulebook doesn't actually need per-article selection (see #1), there's no benefit left to justify that cost.

Net effect on the design's goals: unchanged. Domain knowledge still gets injected (now always-on rather than selected), evidence discipline and the deterministic Confidence Engine are implemented exactly as designed, and the calibration flywheel wiring is unchanged. `event_type` is kept as a real output field (useful for future analytics bucketing) but is now classified by the *same* call rather than a preceding one.

A second, smaller deviation: the design doc listed `event_type`, `prompt_version`, and `knowledge_version` as `AlertCompany` columns. This plan puts them on `Alert` instead, matching where `category` already lives — all three are properties of the analysis run for the whole article, not of any individual company, so storing them once per `Alert` instead of once per `AlertCompany` row avoids repeating identical values across every company in a multi-company alert.

## Global Constraints

- No Alembic. New DB columns go through `app/db.py`'s `_ADDED_COLUMNS` list (guarded `ALTER TABLE`), matching every prior column addition in this codebase.
- No new external services (no vector DB, no graph DB, no task queue). `APScheduler` (already running) remains the only background-job mechanism.
- Every new/changed Pydantic field must have a safe default so **zero existing test files require modification for schema changes alone** — only assertions that actually depended on old LLM-self-rated `confidence_score` values need updating, and those updates are called out explicitly in Task 9.
- `ANALYSIS_INSTRUCTIONS` stays a single concatenated string (not split into multiple message parts) — see the existing A/B-testing comment in `claude_client.py:63-71`; this plan adds content to that same string, never restructures the message shape.
- Match existing test style exactly: `db_session` fixture (in-memory SQLite, see `backend/tests/conftest.py`), `FakeClient`/`FakeToolCall` pattern for LLM mocking (see `backend/tests/test_claude_client.py`), `pytest.approx` for float comparisons.

---

### Task 1: Rulebook module

**Files:**
- Create: `backend/app/reasoning/__init__.py`
- Create: `backend/app/reasoning/rulebook.py`
- Test: `backend/tests/test_rulebook.py`

**Interfaces:**
- Produces: `RULES: dict[str, str]` (rule id → rule text), `RULEBOOK_TEXT: str` (all rules rendered as one block), `get_rule(rule_id: str) -> str | None`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_rulebook.py
from app.reasoning.rulebook import RULEBOOK_TEXT, RULES, get_rule


def test_get_rule_returns_text_for_known_id():
    assert get_rule("RULE_REPO_RATE_CUT") is not None
    assert "banks" in get_rule("RULE_REPO_RATE_CUT").lower() or "banking" in get_rule("RULE_REPO_RATE_CUT").lower()


def test_get_rule_returns_none_for_unknown_id():
    assert get_rule("RULE_DOES_NOT_EXIST") is None


def test_rule_ids_are_uppercase_with_prefix():
    for rule_id in RULES:
        assert rule_id.startswith("RULE_")
        assert rule_id == rule_id.upper()


def test_rulebook_text_contains_every_rule_id():
    for rule_id in RULES:
        assert rule_id in RULEBOOK_TEXT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_rulebook.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reasoning'`

- [ ] **Step 3: Create the package and write the rulebook**

```python
# backend/app/reasoning/__init__.py
```

```python
# backend/app/reasoning/rulebook.py
"""Deterministic financial reasoning rules injected into the analysis prompt
as static reference context. All rules are always present in the prompt
(not selected per-article) -- the content is compact enough that always-on
beats building event-classification infrastructure to select a subset. See
docs/superpowers/specs/2026-07-15-reasoning-engine-upgrade-design.md and the
"Deviation from the design spec" note in this plan's implementation doc.

Each rule has a stable id the analysis model is instructed to cite verbatim
in a company's `evidence_refs` when the rule actually applies -- that
citation is what lets app.reasoning.confidence detect a rulebook match
deterministically, without re-parsing free text.
"""

RULES: dict[str, str] = {
    "RULE_REPO_RATE_CUT": (
        "Repo rate cut: borrowing costs decrease, credit demand may increase. "
        "Likely positive: private banks, housing finance, real estate, consumer "
        "lending, auto financing. Risks: margin compression, deposit repricing, "
        "inflation persistence. Second-order: housing up -> cement up -> steel "
        "up -> construction up."
    ),
    "RULE_REPO_RATE_HIKE": (
        "Repo rate hike: credit demand weakens, borrowing becomes more "
        "expensive. Likely negative: banks (loan growth), housing, auto "
        "demand, consumer discretionary. Potential positive: deposit growth, "
        "net interest margins (context dependent)."
    ),
    "RULE_INFLATION_RISE": (
        "Higher inflation: consumer spending pressure, margin compression, "
        "rate hike probability increases. Beneficiaries may include commodity "
        "producers and select energy companies. Losers may include consumer "
        "discretionary and other rate-sensitive sectors."
    ),
    "RULE_CRUDE_OIL_UP": (
        "Oil price increase: beneficiaries are upstream producers and oil "
        "exploration companies. Potentially negative: airlines, paints, "
        "chemicals, logistics, fuel-intensive manufacturing. Always verify "
        "which specific role a company plays (upstream vs refiner vs "
        "distributor) before applying this -- do not assume every company in "
        "the sector plays the same role."
    ),
    "RULE_CURRENCY_INR_WEAKENS": (
        "INR weakens: possible beneficiaries are IT exporters and pharma "
        "exporters. Potentially negative: heavy importers and oil marketing "
        "companies. INR strengthens: generally the opposite effects."
    ),
    "RULE_GOVERNMENT_CAPEX": (
        "Infrastructure capex increase: likely beneficiaries are cement, "
        "steel, EPC, capital goods, and infrastructure developers. "
        "Propagation: government spending -> projects -> materials -> "
        "logistics."
    ),
    "RULE_EARNINGS": (
        "Earnings beat/miss: direct impact on the reporting company first. "
        "Only reason about competitors if there is specific evidence for "
        "them -- do not assume a peer moves the same way. Always consider "
        "revenue, margins, guidance, order book, and cash flow -- not just "
        "the headline beat/miss number."
    ),
    "RULE_MERGER_ACQUISITION": (
        "Mergers/acquisitions: evaluate acquirer, target, competitors, "
        "suppliers, customers, and regulatory risk separately. Do not assume "
        "a merger is automatically positive for the acquirer -- integration "
        "risk and overpayment risk cut against that."
    ),
    "RULE_BANKING_METRICS": (
        "Banking-specific metrics (credit growth, deposit growth, CASA, NIM, "
        "asset quality, capital adequacy) must be evaluated independently of "
        "each other -- a strong CASA franchise does not imply strong asset "
        "quality, and vice versa."
    ),
}

RULEBOOK_TEXT = "\n".join(f"- {rule_id}: {text}" for rule_id, text in RULES.items())


def get_rule(rule_id: str) -> str | None:
    """Look up a rule's text by its stable id -- used by
    app.reasoning.confidence to detect whether a company's evidence_refs cite
    a real, known rule (vs. an unsupported claim)."""
    return RULES.get(rule_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_rulebook.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/__init__.py backend/app/reasoning/rulebook.py backend/tests/test_rulebook.py
git commit -m "feat: add financial reasoning rulebook module"
```

---

### Task 2: Sector playbooks module

**Files:**
- Create: `backend/app/reasoning/playbooks.py`
- Test: `backend/tests/test_playbooks.py`

**Interfaces:**
- Consumes: `SECTORS` from `app.analysis.schemas` (existing, `backend/app/analysis/schemas.py:5`)
- Produces: `PLAYBOOKS: dict[str, str]` (sector → playbook text), `PLAYBOOKS_TEXT: str`, `get_playbook(sector: str | None) -> str | None`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_playbooks.py
from app.analysis.schemas import SECTORS
from app.reasoning.playbooks import PLAYBOOKS, PLAYBOOKS_TEXT, get_playbook


def test_get_playbook_returns_text_for_known_sector():
    assert get_playbook("banking") is not None
    assert "NIM" in get_playbook("banking")


def test_get_playbook_returns_none_for_no_sector():
    assert get_playbook(None) is None


def test_get_playbook_returns_none_for_unknown_sector():
    assert get_playbook("not_a_real_sector") is None


def test_every_playbook_key_is_a_real_sector():
    # Guards against a typo'd sector key silently never being injected.
    for sector in PLAYBOOKS:
        assert sector in SECTORS


def test_playbooks_text_contains_every_playbook_sector_name():
    for sector in PLAYBOOKS:
        assert sector in PLAYBOOKS_TEXT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_playbooks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reasoning.playbooks'`

- [ ] **Step 3: Write the playbooks module**

```python
# backend/app/reasoning/playbooks.py
"""Sector-specific reasoning playbooks, injected as static reference context
alongside the rulebook (see app.reasoning.rulebook for the always-on
rationale). Keyed by the same lowercase sector values as
app.analysis.schemas.SECTORS -- "other" intentionally has no playbook.
"""

from app.analysis.schemas import SECTORS

PLAYBOOKS: dict[str, str] = {
    "banking": (
        "Banking: KPIs are NIM, CASA, credit growth, deposit growth, GNPA, "
        "NNPA, ROA, ROE. Bullish: repo cuts (context dependent), credit "
        "growth, lower NPAs, strong deposit franchise. Bearish: asset "
        "quality deterioration, weak credit demand, regulatory tightening."
    ),
    "it": (
        "IT services: revenue driven by global enterprise spending, "
        "outsourcing, cloud migration, AI adoption. Sensitive to USD/INR, US "
        "recession risk, technology budgets. KPIs: deal wins, attrition, "
        "EBIT margin, utilization."
    ),
    "pharma": (
        "Pharma: drivers are USFDA approvals, generic launches, export "
        "demand, currency. Risks: regulatory actions, pricing pressure."
    ),
    "fmcg": (
        "FMCG: drivers are rural demand, urban demand, inflation, commodity "
        "costs. Watch gross margins and volume growth separately -- a price "
        "hike can grow margins while volume falls."
    ),
    "auto": (
        "Auto: drivers are consumer confidence, interest rates, steel and "
        "aluminium input costs, fuel prices. KPIs: volume growth, dealer "
        "inventory."
    ),
    "oil_gas": (
        "Oil & gas: sub-sectors (upstream, midstream, downstream) react "
        "differently to the same crude move -- upstream/exploration "
        "benefits from higher crude, downstream/refining margins depend on "
        "the crude-product spread, not crude direction alone. Also "
        "sensitive to government fuel-pricing policy."
    ),
    "metals": (
        "Metals: watch China demand, domestic infrastructure spend, and "
        "commodity prices. Propagation: infrastructure spend up -> steel up "
        "-> mining up."
    ),
    "telecom": (
        "Telecom: drivers are ARPU, subscriber growth, spectrum costs, and "
        "capex cycles."
    ),
    "infra": (
        "Infrastructure/industrials: drivers are government capex, private "
        "capex cycle, input costs (cement, steel), and execution/order-book "
        "visibility."
    ),
}

PLAYBOOKS_TEXT = "\n".join(f"- {sector}: {text}" for sector, text in PLAYBOOKS.items())


def get_playbook(sector: str | None) -> str | None:
    if sector is None:
        return None
    return PLAYBOOKS.get(sector)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_playbooks.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/playbooks.py backend/tests/test_playbooks.py
git commit -m "feat: add sector playbooks module"
```

---

### Task 3: Deterministic Confidence Engine

**Files:**
- Create: `backend/app/reasoning/confidence.py`
- Test: `backend/tests/test_confidence.py`

**Interfaces:**
- Produces: `ConfidenceResult` (dataclass: `score: int`, `band: str`, `contributors: list[str]`, `penalties: list[str]`), `compute_confidence(**kwargs) -> ConfidenceResult`, `source_credibility(source: str) -> float`, `WEIGHT_HISTORICAL_CALIBRATION` / `WEIGHT_EVIDENCE_COMPLETENESS` / `WEIGHT_RULEBOOK_MATCH` / `WEIGHT_SOURCE_CREDIBILITY` / `WEIGHT_REASONING_CONSISTENCY` / `WEIGHT_DATA_FRESHNESS` (floats), `CALIBRATION_SAMPLE_THRESHOLD` (int, mirrors `app.calibration.blender.CALIBRATION_SAMPLE_THRESHOLD`)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_confidence.py
import pytest

from app.reasoning.confidence import (
    WEIGHT_DATA_FRESHNESS,
    WEIGHT_EVIDENCE_COMPLETENESS,
    WEIGHT_HISTORICAL_CALIBRATION,
    WEIGHT_REASONING_CONSISTENCY,
    WEIGHT_RULEBOOK_MATCH,
    WEIGHT_SOURCE_CREDIBILITY,
    _band,
    compute_confidence,
    source_credibility,
)


def test_weights_sum_to_one():
    total = (
        WEIGHT_HISTORICAL_CALIBRATION + WEIGHT_EVIDENCE_COMPLETENESS + WEIGHT_RULEBOOK_MATCH
        + WEIGHT_SOURCE_CREDIBILITY + WEIGHT_REASONING_CONSISTENCY + WEIGHT_DATA_FRESHNESS
    )
    assert total == pytest.approx(1.0)


def test_band_boundaries():
    assert _band(0) == "LOW"
    assert _band(39) == "LOW"
    assert _band(40) == "MODERATE"
    assert _band(69) == "MODERATE"
    assert _band(70) == "HIGH"
    assert _band(89) == "HIGH"
    assert _band(90) == "VERY_HIGH"
    assert _band(100) == "VERY_HIGH"


def test_weak_inputs_score_low():
    result = compute_confidence(
        calibration_sample_count=0, calibration_hit_rate=None,
        claim_count=3, evidence_ref_count=0, rule_matched=False,
        source_credibility=0.7, reasoning_consistent=True, article_age_hours=0,
    )
    assert result.score == 27
    assert result.band == "LOW"
    assert any("historical" in p.lower() for p in result.penalties)
    assert any("evidence" in p.lower() or "claim" in p.lower() for p in result.penalties)
    assert any("rulebook" in p.lower() or "rule" in p.lower() for p in result.penalties)


def test_strong_inputs_score_very_high():
    result = compute_confidence(
        calibration_sample_count=10, calibration_hit_rate=0.9,
        claim_count=2, evidence_ref_count=2, rule_matched=True,
        source_credibility=0.85, reasoning_consistent=True, article_age_hours=1,
    )
    assert result.score == 95
    assert result.band == "VERY_HIGH"
    assert any("calibration" in c.lower() for c in result.contributors)
    assert any("rule" in c.lower() for c in result.contributors)


def test_zero_claims_treated_as_fully_covered_not_penalized():
    result = compute_confidence(
        calibration_sample_count=0, calibration_hit_rate=None,
        claim_count=0, evidence_ref_count=0, rule_matched=False,
        source_credibility=0.7, reasoning_consistent=True, article_age_hours=0,
    )
    assert not any("evidence" in p.lower() and "claims" in p.lower() for p in result.penalties)


def test_reasoning_inconsistency_is_penalized():
    result = compute_confidence(
        calibration_sample_count=0, calibration_hit_rate=None,
        claim_count=0, evidence_ref_count=0, rule_matched=False,
        source_credibility=0.7, reasoning_consistent=False, article_age_hours=0,
    )
    assert any("inconsistent" in p.lower() for p in result.penalties)


def test_score_is_clamped_to_0_100_range():
    result = compute_confidence(
        calibration_sample_count=100, calibration_hit_rate=1.0,
        claim_count=1, evidence_ref_count=1, rule_matched=True,
        source_credibility=1.0, reasoning_consistent=True, article_age_hours=0,
    )
    assert 0 <= result.score <= 100


def test_source_credibility_known_and_default():
    assert source_credibility("economic_times") == pytest.approx(0.85)
    assert source_credibility("moneycontrol") == pytest.approx(0.8)
    assert source_credibility("business_standard") == pytest.approx(0.8)
    assert source_credibility("some_unknown_source") == pytest.approx(0.7)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_confidence.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reasoning.confidence'`

- [ ] **Step 3: Write the Confidence Engine**

```python
# backend/app/reasoning/confidence.py
"""Deterministic Confidence Engine. Computes confidence_score from evidence,
calibration history, and reasoning-quality signals instead of asking the LLM
to self-rate its own confidence -- see
docs/superpowers/specs/2026-07-15-reasoning-engine-upgrade-design.md.

compute_confidence is a pure function: every input is a plain value the
caller has already looked up (from CalibrationSample stats, the resolved
company entry, and the source article), so this module has no DB or network
dependency and is fully unit-testable with fixed inputs.
"""

from dataclasses import dataclass, field

# Weights sum to 1.0. Kept as separate named constants (not one dict literal)
# so a future calibration-health review can retune a single weight without
# hunting through compute_confidence's body.
WEIGHT_HISTORICAL_CALIBRATION = 0.30
WEIGHT_EVIDENCE_COMPLETENESS = 0.20
WEIGHT_RULEBOOK_MATCH = 0.20
WEIGHT_SOURCE_CREDIBILITY = 0.10
WEIGHT_REASONING_CONSISTENCY = 0.10
WEIGHT_DATA_FRESHNESS = 0.10

# Mirrors app.calibration.blender.CALIBRATION_SAMPLE_THRESHOLD -- duplicated
# rather than imported to keep this module dependency-free (no DB imports);
# both must be changed together if ever retuned.
CALIBRATION_SAMPLE_THRESHOLD = 5

# Static per-source scores for known RSS feeds (see
# app/ingestion/sources.py::RSS_FEEDS). Deliberately small and roughly equal
# for now -- real differentiation should come from calibration-health data
# once enough volume exists per source, not from an editorial guess.
SOURCE_CREDIBILITY: dict[str, float] = {
    "economic_times": 0.85,
    "moneycontrol": 0.8,
    "business_standard": 0.8,
}
DEFAULT_SOURCE_CREDIBILITY = 0.7


def source_credibility(source: str) -> float:
    return SOURCE_CREDIBILITY.get(source, DEFAULT_SOURCE_CREDIBILITY)


@dataclass
class ConfidenceResult:
    score: int  # 0-100
    band: str  # LOW | MODERATE | HIGH | VERY_HIGH
    contributors: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)


def _band(score: int) -> str:
    if score < 40:
        return "LOW"
    if score < 70:
        return "MODERATE"
    if score < 90:
        return "HIGH"
    return "VERY_HIGH"


def compute_confidence(
    *,
    calibration_sample_count: int,
    calibration_hit_rate: float | None,
    claim_count: int,
    evidence_ref_count: int,
    rule_matched: bool,
    source_credibility: float,
    reasoning_consistent: bool,
    article_age_hours: float,
) -> ConfidenceResult:
    contributors: list[str] = []
    penalties: list[str] = []

    # Historical calibration: 0 until enough real-outcome samples exist (same
    # threshold app.calibration.blender uses for magnitude blending), then
    # hit_rate itself IS the 0-1 component score.
    if calibration_sample_count < CALIBRATION_SAMPLE_THRESHOLD or calibration_hit_rate is None:
        historical_component = 0.0
        penalties.append(
            f"No historical calibration yet ({calibration_sample_count} samples, "
            f"need {CALIBRATION_SAMPLE_THRESHOLD})"
        )
    else:
        historical_component = calibration_hit_rate
        contributors.append(
            f"Historical calibration: {calibration_hit_rate:.0%} hit rate over "
            f"{calibration_sample_count} samples"
        )

    # Evidence completeness: fraction of claims that cite at least one piece
    # of evidence. claim_count == 0 is treated as fully covered (nothing to
    # cite), not a penalty for an empty claim list.
    if claim_count == 0:
        evidence_component = 1.0
    else:
        evidence_component = min(1.0, evidence_ref_count / claim_count)
    if evidence_component >= 0.8:
        contributors.append(f"Evidence cited for {evidence_ref_count}/{max(claim_count, 1)} claims")
    else:
        penalties.append(f"Only {evidence_ref_count}/{max(claim_count, 1)} claims cite evidence")

    rule_component = 1.0 if rule_matched else 0.0
    if rule_matched:
        contributors.append("Matched a known rulebook rule")
    else:
        penalties.append("No rulebook rule matched -- generic reasoning only")

    source_component = max(0.0, min(1.0, source_credibility))

    consistency_component = 1.0 if reasoning_consistent else 0.0
    if not reasoning_consistent:
        penalties.append("Reasoning flagged as internally inconsistent")

    # Freshness: linear decay to 0 over 7 days (168h) -- older than that
    # contributes nothing, since news relevance genuinely fades.
    freshness_component = max(0.0, min(1.0, 1 - (article_age_hours / 168)))
    if freshness_component < 0.5:
        penalties.append("Article is more than 3.5 days old")

    raw = (
        historical_component * WEIGHT_HISTORICAL_CALIBRATION
        + evidence_component * WEIGHT_EVIDENCE_COMPLETENESS
        + rule_component * WEIGHT_RULEBOOK_MATCH
        + source_component * WEIGHT_SOURCE_CREDIBILITY
        + consistency_component * WEIGHT_REASONING_CONSISTENCY
        + freshness_component * WEIGHT_DATA_FRESHNESS
    )
    score = max(0, min(100, round(raw * 100)))

    return ConfidenceResult(score=score, band=_band(score), contributors=contributors, penalties=penalties)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_confidence.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/confidence.py backend/tests/test_confidence.py
git commit -m "feat: add deterministic Confidence Engine"
```

---

### Task 4: Calibration health lookup

**Files:**
- Modify: `backend/app/calibration/blender.py`
- Test: `backend/tests/test_blender.py`

**Interfaces:**
- Consumes: `Alert`, `AlertCompany`, `CalibrationSample` from `app.models` (existing, `backend/app/models.py`)
- Produces: `get_calibration_health(session, category: str, company_id: int) -> dict` returning `{"sample_count": int, "hit_rate": float | None, "mean_error": float | None}`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_blender.py`:

```python
from app.calibration.blender import get_calibration_health
from app.models import Alert, AlertCompany, Article, Company


def test_calibration_health_returns_zero_stats_with_no_samples(db_session):
    result = get_calibration_health(db_session, category="oil_energy", company_id=1)
    assert result == {"sample_count": 0, "hit_rate": None, "mean_error": None}


def test_calibration_health_computes_hit_rate_and_mean_error(db_session):
    company = Company(ticker="X.NS", name="X", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()
    article = Article(source="test", url="https://example.com/health", title="t")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()

    # Two predictions, both originally "bullish": one correct (actual also
    # bullish), one wrong (actual bearish) -- hit_rate must be 0.5.
    ac1 = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="x", basis="direct_mention",
    )
    ac2 = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="x", basis="direct_mention",
    )
    db_session.add_all([ac1, ac2])
    db_session.commit()

    db_session.add(CalibrationSample(
        alert_company_id=ac1.id, category="oil_energy", company_id=company.id,
        direction="bullish", magnitude_actual=5.0, horizon_days=1,
    ))
    db_session.add(CalibrationSample(
        alert_company_id=ac2.id, category="oil_energy", company_id=company.id,
        direction="bearish", magnitude_actual=-1.0, horizon_days=1,
    ))
    db_session.commit()

    result = get_calibration_health(db_session, category="oil_energy", company_id=company.id)

    assert result["sample_count"] == 2
    assert result["hit_rate"] == pytest.approx(0.5)
    # predicted_mid = (2.0+4.0)/2 = 3.0 for both rows.
    # errors: |5.0-3.0|=2.0, |-1.0-3.0|=4.0 -> mean = 3.0
    assert result["mean_error"] == pytest.approx(3.0)


def test_calibration_health_excludes_other_category_and_company(db_session):
    company = Company(ticker="Y.NS", name="Y", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()
    article = Article(source="test", url="https://example.com/health2", title="t")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()

    matching = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=1.0, rationale="x", basis="direct_mention",
    )
    db_session.add(matching)
    db_session.commit()
    db_session.add(CalibrationSample(
        alert_company_id=matching.id, category="oil_energy", company_id=company.id,
        direction="bullish", magnitude_actual=1.0, horizon_days=1,
    ))
    # Noise: different category, same company -- must not be counted.
    db_session.add(CalibrationSample(
        alert_company_id=matching.id, category="banking", company_id=company.id,
        direction="bearish", magnitude_actual=-99.0, horizon_days=1,
    ))
    db_session.commit()

    result = get_calibration_health(db_session, category="oil_energy", company_id=company.id)

    assert result["sample_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_blender.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_calibration_health'`

- [ ] **Step 3: Implement get_calibration_health**

```python
# backend/app/calibration/blender.py
import statistics

from sqlalchemy.orm import Session

from app.models import AlertCompany, CalibrationSample

CALIBRATION_SAMPLE_THRESHOLD = 5


def get_calibrated_magnitude(session: Session, category: str, company_id: int) -> tuple[float, float] | None:
    """Blend historical outcomes for a (category, company) pair into a magnitude
    range. Returns ``(low, high)`` = ``(mean - pstdev, mean + pstdev)`` over the
    actual moves once at least ``CALIBRATION_SAMPLE_THRESHOLD`` samples exist,
    else ``None`` (caller keeps the LLM's own estimate).
    """
    samples = (
        session.query(CalibrationSample)
        .filter(CalibrationSample.category == category)
        .filter(CalibrationSample.company_id == company_id)
        .all()
    )
    if len(samples) < CALIBRATION_SAMPLE_THRESHOLD:
        return None

    values = [s.magnitude_actual for s in samples]
    mean = statistics.mean(values)
    pstdev = statistics.pstdev(values)  # population stdev — full sample set, not a sample of a larger population
    if pstdev == 0:
        return (mean, mean)
    return (mean - pstdev, mean + pstdev)


def get_calibration_health(session: Session, category: str, company_id: int) -> dict:
    """Summarize past-outcome accuracy for a (category, company) pair, for the
    Confidence Engine's historical-calibration component (app.reasoning.
    confidence.compute_confidence). Unlike get_calibrated_magnitude, this
    needs the ORIGINAL predicted direction to compute a hit rate --
    CalibrationSample only stores the actual outcome, so it joins back to
    the originating AlertCompany row.
    """
    rows = (
        session.query(CalibrationSample, AlertCompany)
        .join(AlertCompany, CalibrationSample.alert_company_id == AlertCompany.id)
        .filter(CalibrationSample.category == category)
        .filter(CalibrationSample.company_id == company_id)
        .all()
    )
    sample_count = len(rows)
    if sample_count == 0:
        return {"sample_count": 0, "hit_rate": None, "mean_error": None}

    hits = sum(1 for sample, ac in rows if sample.direction == ac.direction)
    hit_rate = hits / sample_count

    errors = [abs(sample.magnitude_actual - (ac.magnitude_low + ac.magnitude_high) / 2) for sample, ac in rows]
    mean_error = statistics.mean(errors)

    return {"sample_count": sample_count, "hit_rate": hit_rate, "mean_error": mean_error}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_blender.py -v`
Expected: PASS (all tests, including the 3 new ones and the pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/calibration/blender.py backend/tests/test_blender.py
git commit -m "feat: add calibration health lookup for the Confidence Engine"
```

---

### Task 5: Extend schemas with evidence-discipline fields

**Files:**
- Modify: `backend/app/analysis/schemas.py`
- Create: `backend/tests/test_schemas.py`

**Interfaces:**
- Produces: `EVENT_TYPES: list[str]`, `CompanyMention` with new fields `reasons: list[str]`, `evidence_refs: list[str]`, `risks: list[str]`, `assumptions: list[str]`, `unknowns: list[str]`, `alternative_hypothesis: str | None`, `confidence_score: int | None` (changed from required `int`), `AnalysisOutput.event_type: str | None`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_schemas.py
from app.analysis.schemas import EVENT_TYPES, AnalysisOutput, CompanyMention


def test_company_mention_defaults_for_new_evidence_fields():
    mention = CompanyMention(
        name="X", is_direct=True, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
    )
    assert mention.confidence_score is None
    assert mention.reasons == []
    assert mention.evidence_refs == []
    assert mention.risks == []
    assert mention.assumptions == []
    assert mention.unknowns == []
    assert mention.alternative_hypothesis is None


def test_company_mention_still_accepts_an_explicit_confidence_score():
    # Backward compatibility: older stored data / tests that still pass an
    # int must keep validating.
    mention = CompanyMention(
        name="X", is_direct=True, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        confidence_score=85,
    )
    assert mention.confidence_score == 85


def test_analysis_output_event_type_defaults_to_none():
    output = AnalysisOutput(category="oil_energy", companies=[])
    assert output.event_type is None


def test_event_types_are_lowercase_with_underscores_only():
    for value in EVENT_TYPES:
        assert value == value.lower()
        assert " " not in value
    assert "other" in EVENT_TYPES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_schemas.py -v`
Expected: FAIL with `ImportError: cannot import name 'EVENT_TYPES'`

- [ ] **Step 3: Update schemas.py**

```python
# backend/app/analysis/schemas.py
from typing import Optional

from pydantic import BaseModel

SECTORS = ["oil_gas", "banking", "auto", "it", "pharma", "fmcg", "metals", "telecom", "infra", "other"]
TIME_HORIZONS = ["Immediate", "Short-Term", "Medium-Term", "Long-Term"]
EVENT_TYPES = [
    "repo_rate_change", "inflation", "crude_oil", "currency_move",
    "government_spending", "earnings", "merger_acquisition", "banking_metrics",
    "other",
]


class CompanyMention(BaseModel):
    name: str
    ticker: Optional[str] = None
    is_direct: bool
    sector: Optional[str] = None
    direction: str  # bullish | bearish
    magnitude_low: float
    magnitude_high: float
    rationale: str
    # Short, scannable version of `rationale` for the feed UI -- the full
    # paragraph is kept for anyone who wants the depth, but a feed of alerts
    # is unreadable if every card is a paragraph. Defaults to empty for any
    # caller not yet passing it (older tests, older stored data).
    key_points: list[str] = []
    # No longer LLM-provided -- computed deterministically by
    # app.reasoning.confidence.compute_confidence and overwritten before
    # persistence (see app/pipeline.py::_persist_alert). Optional here only
    # so any caller not yet passing it (older tests, older stored data)
    # still validates.
    confidence_score: Optional[int] = None
    # Exactly one of TIME_HORIZONS -- when the mechanism described in
    # `rationale` actually plays out, not how soon the news was published.
    time_horizon: str
    # Evidence-discipline fields (see docs/superpowers/specs/2026-07-15-
    # reasoning-engine-upgrade-design.md). All default to empty/None so
    # existing callers that don't pass them still validate.
    reasons: list[str] = []
    evidence_refs: list[str] = []
    risks: list[str] = []
    assumptions: list[str] = []
    unknowns: list[str] = []
    alternative_hypothesis: Optional[str] = None


class AnalysisOutput(BaseModel):
    category: str
    companies: list[CompanyMention]
    # Article-level event classification, parallel to `category`. Optional
    # at the pydantic layer (defaults to None) for backward compatibility;
    # the tool schema sent to the LLM (RECORD_ANALYSIS_TOOL) still requires
    # it on every real call.
    event_type: Optional[str] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_schemas.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full existing test suite to confirm zero regressions from this schema change**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS (all existing tests still pass — every new/changed field has a safe default, so no existing fixture construction breaks)

- [ ] **Step 6: Commit**

```bash
git add backend/app/analysis/schemas.py backend/tests/test_schemas.py
git commit -m "feat: add event_type and evidence-discipline fields to analysis schemas"
```

---

### Task 6: Inject rulebook/playbooks into the analysis prompt, add evidence-discipline tool fields

**Files:**
- Modify: `backend/app/analysis/claude_client.py`
- Test: `backend/tests/test_claude_client.py` (add new tests only — existing tests are unaffected, verified in Step 4)

**Interfaces:**
- Consumes: `RULEBOOK_TEXT` from `app.reasoning.rulebook` (Task 1), `PLAYBOOKS_TEXT` from `app.reasoning.playbooks` (Task 2), `EVENT_TYPES` from `app.analysis.schemas` (Task 5)
- Produces: updated `RECORD_ANALYSIS_TOOL` (drops `confidence_score`, adds `event_type` at top level and `reasons`/`evidence_refs`/`risks`/`assumptions`/`unknowns`/`alternative_hypothesis` per company), updated `ANALYSIS_INSTRUCTIONS`. `analyze_article`'s signature is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_claude_client.py`:

```python
def test_record_analysis_tool_no_longer_requires_confidence_score():
    from app.analysis.claude_client import RECORD_ANALYSIS_TOOL
    company_props = RECORD_ANALYSIS_TOOL["function"]["parameters"]["properties"]["companies"]["items"]
    assert "confidence_score" not in company_props["properties"]
    assert "confidence_score" not in company_props["required"]


def test_record_analysis_tool_requires_evidence_discipline_fields():
    from app.analysis.claude_client import RECORD_ANALYSIS_TOOL
    company_props = RECORD_ANALYSIS_TOOL["function"]["parameters"]["properties"]["companies"]["items"]
    for field in ["reasons", "evidence_refs", "risks", "assumptions", "unknowns", "alternative_hypothesis"]:
        assert field in company_props["properties"]
        assert field in company_props["required"]


def test_record_analysis_tool_requires_event_type_at_top_level():
    from app.analysis.claude_client import RECORD_ANALYSIS_TOOL
    top_level = RECORD_ANALYSIS_TOOL["function"]["parameters"]
    assert "event_type" in top_level["properties"]
    assert "event_type" in top_level["required"]


def test_analyze_article_parses_new_evidence_fields_when_present():
    fake_output = {
        "category": "oil_energy",
        "event_type": "crude_oil",
        "companies": [{
            "name": "Reliance Industries", "ticker": "RELIANCE.NS", "is_direct": True, "sector": None,
            "direction": "bullish", "magnitude_low": 2.0, "magnitude_high": 4.0,
            "rationale": "Top refiner benefits from crude price spike.",
            "key_points": ["Crude spikes"], "time_horizon": "Short-Term",
            "reasons": ["Refining margins widen on crude spike."],
            "evidence_refs": ["RULE_CRUDE_OIL_UP"],
            "risks": ["Margin reversal if crude falls back."],
            "assumptions": ["Crude stays elevated for the quarter."],
            "unknowns": ["Whether this is a durable supply shock or a spike."],
            "alternative_hypothesis": "Market has already priced this in.",
        }],
    }
    client = FakeClient(fake_output)

    result = analyze_article(client, title="Oil prices spike", content="crude oil markets react")

    assert result.event_type == "crude_oil"
    company = result.companies[0]
    assert company.reasons == ["Refining margins widen on crude spike."]
    assert company.evidence_refs == ["RULE_CRUDE_OIL_UP"]
    assert company.risks == ["Margin reversal if crude falls back."]
    assert company.confidence_score is None  # no longer LLM-provided
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_claude_client.py -v -k "evidence_discipline or event_type or new_evidence"`
Expected: FAIL — `confidence_score` still present/required, `event_type`/`reasons`/`evidence_refs` etc. not yet in the tool schema.

- [ ] **Step 3: Update claude_client.py**

Edit `RECORD_ANALYSIS_TOOL` in `backend/app/analysis/claude_client.py`:

```python
from app.analysis.schemas import EVENT_TYPES, SECTORS, TIME_HORIZONS, AnalysisOutput
from app.reasoning.playbooks import PLAYBOOKS_TEXT
from app.reasoning.rulebook import RULEBOOK_TEXT
```

Replace the `import` line at the top of the file (`from app.analysis.schemas import SECTORS, TIME_HORIZONS, AnalysisOutput`) with the three-line block above.

Replace rule 9 (the `confidence_score` rule) and everything from rule 10 onward in `ANALYSIS_INSTRUCTIONS` — i.e. replace this existing tail of the string (from `"9. Also set confidence_score..."` through the trailing `"\n\n"`) with:

```python
    "9. Classify this article's overall event_type as exactly one of the "
    "values listed below -- lowercase-with-underscores, exact spelling. If "
    "nothing matches, use \"other\":\n"
    f"{', '.join(EVENT_TYPES)}\n"
    "10. Also set time_horizon to exactly one of: Immediate (already priced "
    "in, or resolves within days), Short-Term (plays out over the next few "
    "weeks to a quarter), Medium-Term (multi-quarter), or Long-Term "
    "(structural, multi-year). Base it on when the mechanism you described "
    "in the rationale actually plays out, not on how recently the news was "
    "published.\n"
    "11. Consult the ECONOMIC REASONING RULES and SECTOR PLAYBOOKS reference "
    "blocks below. If a rule genuinely applies to a company's situation, use "
    "it to strengthen your rationale -- and include its rule id (e.g. "
    "RULE_REPO_RATE_CUT) verbatim as one entry in that company's "
    "evidence_refs. Do not force-fit a rule that doesn't actually apply just "
    "to have one.\n"
    f"ECONOMIC REASONING RULES:\n{RULEBOOK_TEXT}\n\n"
    f"SECTOR PLAYBOOKS:\n{PLAYBOOKS_TEXT}\n"
    "12. For each company, fill in reasons: a list of 1-4 short, distinct "
    "reasons (each a full but concise sentence) supporting your direction "
    "call -- this decomposes `rationale` into discrete, individually-"
    "citable claims rather than one paragraph.\n"
    "13. Fill in evidence_refs: for EACH entry in `reasons`, cite what "
    "supports it -- either a rule id from ECONOMIC REASONING RULES above "
    "(e.g. \"RULE_REPO_RATE_CUT\"), a quoted or closely paraphrased fact "
    "from the article text (prefix with \"article: \"), or a specific "
    "historical precedent you actually know (prefix with \"historical: \", "
    "e.g. \"historical: 2019 repo rate cut lifted HDFC Bank credit "
    "growth\"). Every claim in `reasons` should be traceable to at least one "
    "entry here -- do not state a reason you cannot support this way.\n"
    "14. Fill in risks: 0-3 short, specific risks that could invalidate "
    "this call (empty list only if you genuinely cannot think of a real "
    "one -- rare). And assumptions: 0-3 things you are assuming to be true "
    "that, if wrong, would change the call. And unknowns: 0-3 pieces of "
    "information you don't have that would make this call more reliable if "
    "you did (empty is fine when the picture is genuinely complete).\n"
    "15. Fill in alternative_hypothesis: one sentence describing a "
    "plausible competing interpretation of this same event for this "
    "company -- even a weaker one you ultimately reject. Required even when "
    "you're confident in the primary call; if you truly see no credible "
    "alternative, state why (e.g. \"No credible alternative -- the "
    "mechanism is direct and well-precedented.\").\n\n"
```

This means rule 9's old body (`"Also set confidence_score..."`) is deleted entirely — `confidence_score` is no longer requested from the model anywhere in `ANALYSIS_INSTRUCTIONS`.

Replace `RECORD_ANALYSIS_TOOL` entirely with:

```python
RECORD_ANALYSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "record_analysis",
        "description": "Record which companies are affected by this news article and how.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "event_type": {"type": ["string", "null"], "enum": EVENT_TYPES + [None]},
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
                            "rationale": {
                                "type": "string",
                                "description": (
                                    "Company-specific reasoning for THIS company only, drawing "
                                    "on what you actually know about it -- its specific role "
                                    "within its business (e.g. upstream producer vs refiner vs "
                                    "distributor vs miner -- never assume every company in a "
                                    "sector plays the same role), its market positioning (e.g. "
                                    "market leader vs smaller player, export-oriented vs "
                                    "domestic-focused, balance-sheet strength), and, when you "
                                    "genuinely know of one, a relevant precedent (how this "
                                    "company or a directly comparable one actually moved on a "
                                    "similar past event). Never write a sentence generic enough "
                                    "that it could be copy-pasted onto a different company in "
                                    "the same sector -- if you catch yourself doing that, you "
                                    "need is_direct=true with an actually distinct mechanism "
                                    "per company, not a shared sector-level rationale."
                                ),
                            },
                            "key_points": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "2-4 short bullet fragments (not full sentences, max ~12 "
                                    "words each) that compress `rationale` into only the "
                                    "essential facts -- for a feed UI where nobody reads a "
                                    "full paragraph per company."
                                ),
                            },
                            "time_horizon": {"type": "string", "enum": TIME_HORIZONS},
                            "reasons": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "1-4 short, distinct, individually-citable reasons supporting the direction call.",
                            },
                            "evidence_refs": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "One entry per `reasons` item: a RULE_ id from ECONOMIC "
                                    "REASONING RULES, an \"article: ...\" quote/paraphrase, or a "
                                    "\"historical: ...\" precedent."
                                ),
                            },
                            "risks": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "0-3 specific risks that could invalidate this call.",
                            },
                            "assumptions": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "0-3 things assumed true that, if wrong, would change the call.",
                            },
                            "unknowns": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "0-3 pieces of missing information that would make this call more reliable.",
                            },
                            "alternative_hypothesis": {
                                "type": "string",
                                "description": "One sentence describing a plausible competing interpretation, or why none is credible.",
                            },
                        },
                        "required": [
                            "name", "is_direct", "direction", "magnitude_low", "magnitude_high",
                            "rationale", "key_points", "time_horizon", "reasons", "evidence_refs",
                            "risks", "assumptions", "unknowns", "alternative_hypothesis",
                        ],
                    },
                },
            },
            "required": ["category", "event_type", "companies"],
        },
    },
}
```

- [ ] **Step 4: Run the new tests, then the full file's existing tests**

Run: `cd backend && python -m pytest tests/test_claude_client.py -v`
Expected: PASS — all new tests pass, and every pre-existing test in this file also still passes unmodified (they construct fake tool-output dicts directly and validate through `CompanyMention`/`AnalysisOutput`, which don't enforce the tool's JSON-schema `required` list — only the new fields' pydantic defaults matter, and those are all backward-compatible per Task 5).

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/analysis/claude_client.py backend/tests/test_claude_client.py
git commit -m "feat: inject rulebook/playbooks into analysis prompt, add evidence-discipline tool fields"
```

---

### Task 7: Carry evidence-discipline fields through company resolution

**Files:**
- Modify: `backend/app/companies/resolution.py`
- Test: `backend/tests/test_resolution.py`

**Interfaces:**
- Produces: `_to_resolved` now includes `reasons`, `evidence_refs`, `risks`, `assumptions`, `unknowns`, `alternative_hypothesis` in its returned dict (in addition to the existing keys)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_resolution.py`:

```python
def test_resolve_carries_evidence_discipline_fields_through(db_session):
    company = _make_company(db_session, "RELIANCE.NS", "Reliance Industries", "oil_gas", 1.0)
    mention = CompanyMention(
        name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
        direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        time_horizon="Short-Term",
        reasons=["Refining margins widen."],
        evidence_refs=["RULE_CRUDE_OIL_UP"],
        risks=["Margin reversal."],
        assumptions=["Crude stays elevated."],
        unknowns=["Duration of the spike."],
        alternative_hypothesis="Already priced in.",
    )

    resolved = resolve_companies(db_session, [mention])

    assert resolved[0]["reasons"] == ["Refining margins widen."]
    assert resolved[0]["evidence_refs"] == ["RULE_CRUDE_OIL_UP"]
    assert resolved[0]["risks"] == ["Margin reversal."]
    assert resolved[0]["assumptions"] == ["Crude stays elevated."]
    assert resolved[0]["unknowns"] == ["Duration of the spike."]
    assert resolved[0]["alternative_hypothesis"] == "Already priced in."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_resolution.py -v -k evidence_discipline`
Expected: FAIL with `KeyError: 'reasons'`

- [ ] **Step 3: Update `_to_resolved`**

```python
# backend/app/companies/resolution.py, replace _to_resolved:
def _to_resolved(company: Company, mention: CompanyMention, basis: str) -> dict:
    return {
        "company_id": company.id,
        "direction": mention.direction,
        "magnitude_low": mention.magnitude_low,
        "magnitude_high": mention.magnitude_high,
        "rationale": mention.rationale,
        "key_points": mention.key_points,
        # Raw LLM value if present, otherwise None -- always overwritten by
        # app.reasoning.confidence.compute_confidence before persistence
        # (see app/pipeline.py::_persist_alert).
        "confidence_score": mention.confidence_score,
        "time_horizon": mention.time_horizon,
        "basis": basis,
        "reasons": mention.reasons,
        "evidence_refs": mention.evidence_refs,
        "risks": mention.risks,
        "assumptions": mention.assumptions,
        "unknowns": mention.unknowns,
        "alternative_hypothesis": mention.alternative_hypothesis,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_resolution.py -v`
Expected: PASS (all tests, including pre-existing ones — none of them assert on the resolved dict's exact key set, only on specific keys they care about)

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/resolution.py backend/tests/test_resolution.py
git commit -m "feat: carry evidence-discipline fields through company resolution"
```

---

### Task 8: Add new columns to Alert and AlertCompany

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/db.py`
- Create: `backend/app/reasoning/versions.py`
- Test: `backend/tests/test_models.py` (create if it doesn't already exist; if it does, append)

**Interfaces:**
- Produces: `Alert.event_type`, `Alert.prompt_version`, `Alert.knowledge_version` (all nullable `String`); `AlertCompany.reasons_json`, `.evidence_refs_json`, `.risks_json`, `.assumptions_json`, `.unknowns_json`, `.confidence_band`, `.confidence_contributors_json`, `.confidence_penalties_json`, `.rulebook_ids_json` (all nullable `Text`/`String`), `AlertCompany.alternative_hypothesis` (nullable `Text`). `PROMPT_VERSION: str`, `KNOWLEDGE_VERSION: str` in `app.reasoning.versions`.

- [ ] **Step 1: Check for an existing models test file**

Run: `find backend/tests -iname "test_models*"` (or `Get-ChildItem backend/tests -Filter test_models*` on Windows) — if a file exists, the test in Step 2 gets appended to it instead of creating a new one. Assume it does not exist for the rest of this task; adjust the target path if it does.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_models.py
from app.models import Alert, AlertCompany, Article, Company


def test_alert_has_reasoning_engine_columns(db_session):
    article = Article(source="test", url="https://example.com/models-1", title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(
        article_id=article.id, category="oil_energy",
        event_type="crude_oil", prompt_version="v1", knowledge_version="v1",
    )
    db_session.add(alert)
    db_session.commit()
    db_session.refresh(alert)

    assert alert.event_type == "crude_oil"
    assert alert.prompt_version == "v1"
    assert alert.knowledge_version == "v1"


def test_alert_reasoning_engine_columns_are_nullable(db_session):
    article = Article(source="test", url="https://example.com/models-2", title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()  # must not raise

    assert alert.event_type is None


def test_alert_company_has_evidence_discipline_and_confidence_engine_columns(db_session):
    article = Article(source="test", url="https://example.com/models-3", title="t")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    company = Company(ticker="X.NS", name="X", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
        reasons_json='["a"]', evidence_refs_json='["RULE_X"]', risks_json='[]',
        assumptions_json='[]', unknowns_json='[]', alternative_hypothesis="alt",
        confidence_band="HIGH", confidence_contributors_json='["c"]',
        confidence_penalties_json='[]', rulebook_ids_json='["RULE_X"]',
    )
    db_session.add(ac)
    db_session.commit()  # must not raise
    db_session.refresh(ac)

    assert ac.reasons_json == '["a"]'
    assert ac.confidence_band == "HIGH"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: FAIL with `TypeError: 'event_type' is an invalid keyword argument for Alert`

- [ ] **Step 4: Add the columns to models.py**

```python
# backend/app/models.py -- replace the Alert class:
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
```

```python
# backend/app/models.py -- replace the AlertCompany class:
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

    alert = relationship("Alert", back_populates="companies")
    company = relationship("Company")
```

- [ ] **Step 5: Register the new columns for production/dev SQLite migration**

```python
# backend/app/db.py -- append to _ADDED_COLUMNS:
_ADDED_COLUMNS = [
    ("articles", "image_url", "VARCHAR"),
    ("alert_companies", "key_points_json", "TEXT"),
    ("companies", "isin", "VARCHAR"),
    ("users", "email_alerts_enabled", "INTEGER DEFAULT 1"),
    ("alert_companies", "confidence_score", "INTEGER DEFAULT 50"),
    ("alert_companies", "time_horizon", "VARCHAR DEFAULT 'Short-Term'"),
    ("alerts", "event_type", "VARCHAR"),
    ("alerts", "prompt_version", "VARCHAR"),
    ("alerts", "knowledge_version", "VARCHAR"),
    ("alert_companies", "reasons_json", "TEXT"),
    ("alert_companies", "evidence_refs_json", "TEXT"),
    ("alert_companies", "risks_json", "TEXT"),
    ("alert_companies", "assumptions_json", "TEXT"),
    ("alert_companies", "unknowns_json", "TEXT"),
    ("alert_companies", "alternative_hypothesis", "TEXT"),
    ("alert_companies", "confidence_band", "VARCHAR"),
    ("alert_companies", "confidence_contributors_json", "TEXT"),
    ("alert_companies", "confidence_penalties_json", "TEXT"),
    ("alert_companies", "rulebook_ids_json", "TEXT"),
]
```

- [ ] **Step 6: Add version constants module**

```python
# backend/app/reasoning/versions.py
"""Version stamps logged on every Alert so any analysis can be traced back to
exactly which prompt/rulebook version produced it -- enough for debugging and
future A/B comparison without a full prompt-registry service. Bump these
whenever ANALYSIS_INSTRUCTIONS or the rulebook/playbook content changes
meaningfully; never edit history, only add a new version string.
"""

PROMPT_VERSION = "2026.07.15-reasoning-v2"
KNOWLEDGE_VERSION = "2026.07.15-rulebook-v1"
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Run the full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS (all tests — `db_session`'s in-memory SQLite uses `Base.metadata.create_all`, which creates the new columns directly from the model definitions; `_ADDED_COLUMNS` only matters for pre-existing production/dev database files)

- [ ] **Step 9: Commit**

```bash
git add backend/app/models.py backend/app/db.py backend/app/reasoning/versions.py backend/tests/test_models.py
git commit -m "feat: add reasoning engine columns to Alert and AlertCompany"
```

---

### Task 9: Wire the Confidence Engine and evidence fields into the pipeline

**Files:**
- Modify: `backend/app/pipeline.py`
- Modify: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `compute_confidence`, `source_credibility` from `app.reasoning.confidence` (Task 3); `get_rule` from `app.reasoning.rulebook` (Task 1); `get_calibration_health` from `app.calibration.blender` (Task 4); `PROMPT_VERSION`, `KNOWLEDGE_VERSION` from `app.reasoning.versions` (Task 8)
- Produces: `_persist_alert(session, article, category, entries, event_type=None)` (new `event_type` parameter, default `None` for any future caller that doesn't have one yet); `_decode_json_list(value: str | None) -> list[str]` (new helper, generalizes the existing `decode_key_points`)

- [ ] **Step 1: Update the two assertions that hardcode old LLM-self-rated confidence_score values**

These two tests currently assert `confidence_score` equals whatever the mocked LLM output specified (`85`, `55`). Once this task wires in the deterministic engine, that's no longer true by construction — the exact formula is unit-tested in `test_confidence.py` (Task 3); these integration tests should verify wiring (a score got computed and stored, in valid range) rather than duplicate the formula's exact arithmetic.

In `backend/tests/test_pipeline.py`, in `test_process_new_articles_creates_alert_end_to_end`, replace:
```python
    assert alert_companies[0].confidence_score == 85
```
with:
```python
    # confidence_score is now computed by the deterministic Confidence
    # Engine (app.reasoning.confidence), not the mocked LLM's old value of
    # 85 -- exact formula behavior is covered by test_confidence.py.
    assert 0 <= alert_companies[0].confidence_score <= 100
    assert alert_companies[0].confidence_band in {"LOW", "MODERATE", "HIGH", "VERY_HIGH"}
```

In `test_sector_inference_fan_out_copies_confidence_and_horizon_to_every_row`, replace:
```python
    assert all(r.confidence_score == 55 for r in rows)
```
with:
```python
    # Same reasoning as above -- the Confidence Engine, not the LLM,
    # produces confidence_score now.
    assert all(0 <= r.confidence_score <= 100 for r in rows)
```

- [ ] **Step 2: Write new failing tests for the wiring itself**

Append to `backend/tests/test_pipeline.py`:

```python
def test_process_new_articles_persists_evidence_discipline_fields(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/evidence",
        title="Oil prices spike", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy", event_type="crude_oil",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            time_horizon="Short-Term",
            reasons=["Refining margins widen on crude spike."],
            evidence_refs=["RULE_CRUDE_OIL_UP"],
            risks=["Margin reversal if crude falls back."],
            assumptions=["Crude stays elevated."],
            unknowns=["Duration of the spike."],
            alternative_hypothesis="Already priced in.",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    alert = db_session.query(Alert).one()
    assert alert.event_type == "crude_oil"
    assert alert.prompt_version is not None
    assert alert.knowledge_version is not None

    ac = db_session.query(AlertCompany).one()
    assert pipeline_module._decode_json_list(ac.reasons_json) == ["Refining margins widen on crude spike."]
    assert pipeline_module._decode_json_list(ac.evidence_refs_json) == ["RULE_CRUDE_OIL_UP"]
    assert pipeline_module._decode_json_list(ac.rulebook_ids_json) == ["RULE_CRUDE_OIL_UP"]
    assert ac.alternative_hypothesis == "Already priced in."
    assert ac.confidence_band in {"LOW", "MODERATE", "HIGH", "VERY_HIGH"}
    assert pipeline_module._decode_json_list(ac.confidence_contributors_json) != [] or pipeline_module._decode_json_list(ac.confidence_penalties_json) != []


def test_process_new_articles_reuse_path_carries_evidence_fields(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    first = Article(source="source-a", url="https://example.com/reuse-first", title="Oil prices spike", content="x")
    second = Article(source="source-b", url="https://example.com/reuse-second", title="  OIL PRICES   spike  ", content="x, wire copy")
    db_session.add_all([first, second])
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy", event_type="crude_oil",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            time_horizon="Short-Term",
            reasons=["Refining margins widen."], evidence_refs=["RULE_CRUDE_OIL_UP"],
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 2

    alerts = db_session.query(Alert).order_by(Alert.id).all()
    assert alerts[0].event_type == alerts[1].event_type == "crude_oil"

    acs = db_session.query(AlertCompany).order_by(AlertCompany.id).all()
    assert pipeline_module._decode_json_list(acs[0].reasons_json) == pipeline_module._decode_json_list(acs[1].reasons_json)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_pipeline.py -v -k "evidence_discipline or reuse_path_carries"`
Expected: FAIL — `AttributeError: module 'app.pipeline' has no attribute '_decode_json_list'`, and `Alert.event_type` is `None`.

- [ ] **Step 4: Update pipeline.py**

```python
# backend/app/pipeline.py -- update imports:
import json
import time
from datetime import timedelta

from sqlalchemy.orm import Session

from app.alerting.matcher import match_alert_to_holdings
from app.alerting.sender import send_pending_notifications
from app.analysis.claude_client import analyze_article
from app.calibration.blender import get_calibrated_magnitude, get_calibration_health
from app.companies.history import bulk_past_mentions, mentions_before
from app.companies.market import infer_market
from app.companies.resolution import resolve_companies
from app.filtering.heuristic import filter_new_articles
from app.ingestion.og_image import fetch_og_image
from app.models import Alert, AlertCompany, Article, utcnow
from app.reasoning.confidence import compute_confidence, source_credibility
from app.reasoning.rulebook import get_rule
from app.reasoning.versions import KNOWLEDGE_VERSION, PROMPT_VERSION
from app.ws.manager import manager

DEDUP_LOOKBACK_HOURS = 24


def _decode_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    return json.loads(value)


def decode_key_points(alert_company: AlertCompany) -> list[str]:
    return _decode_json_list(alert_company.key_points_json)
```

Update `_alert_broadcast_payload`'s per-company dict (inside the `"companies": [...]` list comprehension) to add the new fields, so the live websocket push carries the same shape the REST API will (Task 10):

```python
        "companies": [{
            "company_id": ac.company_id,
            "ticker": ac.company.ticker,
            "name": ac.company.name,
            "index_tier": ac.company.index_tier,
            "sector": ac.company.sector,
            "direction": ac.direction,
            "magnitude_low": ac.magnitude_low,
            "magnitude_high": ac.magnitude_high,
            "rationale": ac.rationale,
            "key_points": decode_key_points(ac),
            "basis": ac.basis,
            "confidence": ac.confidence,
            "confidence_score": ac.confidence_score,
            "confidence_band": ac.confidence_band,
            "reasons": _decode_json_list(ac.reasons_json),
            "evidence_refs": _decode_json_list(ac.evidence_refs_json),
            "risks": _decode_json_list(ac.risks_json),
            "assumptions": _decode_json_list(ac.assumptions_json),
            "unknowns": _decode_json_list(ac.unknowns_json),
            "alternative_hypothesis": ac.alternative_hypothesis,
            "market": infer_market(ac.company.ticker),
            "past_mentions": mentions_before(mentions_index, ac.company_id, alert.created_at),
        } for ac in alert.companies],
```

Replace `_persist_alert`:

```python
def _persist_alert(
    session: Session, article: Article, category: str, entries: list[dict], event_type: str | None = None,
) -> Alert:
    """Create the Alert + AlertCompany rows for one article and fan out
    notifications/broadcast. Shared by both the fresh-analysis path and the
    dedup-reuse path -- calibration AND confidence are always looked up/
    computed fresh here (not copied from a reused analysis) so a reused
    alert reflects the current calibration state exactly like a brand new
    analysis would.
    """
    alert = Alert(
        article_id=article.id, category=category, event_type=event_type,
        prompt_version=PROMPT_VERSION, knowledge_version=KNOWLEDGE_VERSION,
    )
    session.add(alert)
    session.flush()

    article_age_hours = (utcnow() - (article.published_at or article.fetched_at)).total_seconds() / 3600

    for entry in entries:
        calibrated = get_calibrated_magnitude(session, category=category, company_id=entry["company_id"])
        if calibrated is not None:
            magnitude_low, magnitude_high = calibrated
            confidence = "calibrated"
        else:
            magnitude_low, magnitude_high = entry["magnitude_low"], entry["magnitude_high"]
            confidence = "llm_estimate"

        reasons = entry.get("reasons") or []
        evidence_refs = entry.get("evidence_refs") or []
        matched_rule_ids = [ref for ref in evidence_refs if get_rule(ref) is not None]
        health = get_calibration_health(session, category=category, company_id=entry["company_id"])

        result = compute_confidence(
            calibration_sample_count=health["sample_count"],
            calibration_hit_rate=health["hit_rate"],
            claim_count=len(reasons),
            evidence_ref_count=len(evidence_refs),
            rule_matched=bool(matched_rule_ids),
            source_credibility=source_credibility(article.source),
            # No contradiction-detection stage exists yet -- always True
            # until one is built (see the design doc's deferred-work list).
            reasoning_consistent=True,
            article_age_hours=article_age_hours,
        )

        session.add(AlertCompany(
            alert_id=alert.id,
            company_id=entry["company_id"],
            direction=entry["direction"],
            magnitude_low=magnitude_low,
            magnitude_high=magnitude_high,
            rationale=entry["rationale"],
            key_points_json=json.dumps(entry.get("key_points") or []),
            confidence_score=result.score,
            time_horizon=entry["time_horizon"],
            basis=entry["basis"],
            confidence=confidence,
            reasons_json=json.dumps(reasons),
            evidence_refs_json=json.dumps(evidence_refs),
            risks_json=json.dumps(entry.get("risks") or []),
            assumptions_json=json.dumps(entry.get("assumptions") or []),
            unknowns_json=json.dumps(entry.get("unknowns") or []),
            alternative_hypothesis=entry.get("alternative_hypothesis"),
            confidence_band=result.band,
            confidence_contributors_json=json.dumps(result.contributors),
            confidence_penalties_json=json.dumps(result.penalties),
            rulebook_ids_json=json.dumps(matched_rule_ids),
        ))

    if article.image_url is None:
        article.image_url = fetch_og_image(article.url)

    article.status = "ANALYZED"
    article.category = category
    session.commit()

    new_notifications = match_alert_to_holdings(session, alert)
    send_pending_notifications(session, new_notifications)
    manager.broadcast_sync(_alert_broadcast_payload(session, alert))
    return alert
```

Update `process_new_articles`'s reuse branch and fresh-analysis branch to build the richer `entries` dicts and pass `event_type`:

```python
    for article in pending:
        reusable_alert = _find_reusable_alert(session, article)
        if reusable_alert is not None:
            entries = [{
                "company_id": ac.company_id, "direction": ac.direction,
                "magnitude_low": ac.magnitude_low, "magnitude_high": ac.magnitude_high,
                "rationale": ac.rationale, "key_points": decode_key_points(ac), "basis": ac.basis,
                "time_horizon": ac.time_horizon,
                "reasons": _decode_json_list(ac.reasons_json),
                "evidence_refs": _decode_json_list(ac.evidence_refs_json),
                "risks": _decode_json_list(ac.risks_json),
                "assumptions": _decode_json_list(ac.assumptions_json),
                "unknowns": _decode_json_list(ac.unknowns_json),
                "alternative_hypothesis": ac.alternative_hypothesis,
            } for ac in reusable_alert.companies]
            _persist_alert(session, article, reusable_alert.category, entries, event_type=reusable_alert.event_type)
            alerts_created += 1
            continue

        analysis = None
        for attempt in range(2):  # try once, retry once
            try:
                analysis = analyze_article(claude_client, article.title, article.content)
                break
            except Exception:
                if attempt == 0:
                    time.sleep(throttle_seconds)
                continue
        time.sleep(throttle_seconds)  # stay under the provider's rate limit before the next article

        if analysis is None:
            article.status = "ANALYSIS_FAILED"
            session.commit()
            continue

        resolved = resolve_companies(session, analysis.companies)
        _persist_alert(session, article, analysis.category, resolved, event_type=analysis.event_type)
        alerts_created += 1
```

(`decode_key_points` in the reuse branch dict no longer needs a `"confidence_score"` key — `_persist_alert` computes it fresh from `compute_confidence` regardless of what's passed in, so the old `"confidence_score": ac.confidence_score` entry in that dict literal is simply removed since it's now unused there.)

- [ ] **Step 5: Run the target tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_pipeline.py -v`
Expected: PASS (all tests, including the two updated assertions and the two new tests)

- [ ] **Step 6: Run the full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: wire Confidence Engine and evidence fields into the analysis pipeline"
```

---

### Task 10: Expose new fields via the alerts API

**Files:**
- Modify: `backend/app/routers/alerts.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Produces: each company object in `GET /api/alerts` and `GET /api/alerts/{id}` responses gains `confidence_band`, `reasons`, `evidence_refs`, `risks`, `assumptions`, `unknowns`, `alternative_hypothesis`; the alert object gains `event_type`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api.py`:

```python
def test_list_alerts_includes_reasoning_engine_fields(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(source="test", url="https://example.com/reasoning-fields", title="Test headline", status="ANALYZED", category="oil_energy")
    db_session.add(article)
    db_session.commit()

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy", event_type="crude_oil")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        basis="direct_mention", confidence="llm_estimate",
        confidence_score=72, confidence_band="HIGH",
        reasons_json='["Refining margins widen."]',
        evidence_refs_json='["RULE_CRUDE_OIL_UP"]',
        risks_json='["Margin reversal."]',
        assumptions_json='["Crude stays elevated."]',
        unknowns_json='["Duration of the spike."]',
        alternative_hypothesis="Already priced in.",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["event_type"] == "crude_oil"
    company_payload = body[0]["companies"][0]
    assert company_payload["confidence_band"] == "HIGH"
    assert company_payload["reasons"] == ["Refining margins widen."]
    assert company_payload["evidence_refs"] == ["RULE_CRUDE_OIL_UP"]
    assert company_payload["risks"] == ["Margin reversal."]
    assert company_payload["assumptions"] == ["Crude stays elevated."]
    assert company_payload["unknowns"] == ["Duration of the spike."]
    assert company_payload["alternative_hypothesis"] == "Already priced in."

    app.dependency_overrides.clear()


def test_list_alerts_defaults_reasoning_engine_fields_for_legacy_rows(db_session):
    # Rows persisted before this feature shipped have NULL in every new
    # column -- the API must degrade to empty lists/None, never 500.
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(source="test", url="https://example.com/legacy-reasoning", title="Legacy", status="ANALYZED", category="oil_energy")
    db_session.add(article)
    db_session.commit()
    company = Company(ticker="LEGACY.NS", name="Legacy Co", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="legacy row",
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["event_type"] is None
    company_payload = body[0]["companies"][0]
    assert company_payload["reasons"] == []
    assert company_payload["evidence_refs"] == []
    assert company_payload["confidence_band"] is None
    assert company_payload["alternative_hypothesis"] is None

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_api.py -v -k reasoning_engine`
Expected: FAIL — `KeyError: 'event_type'` (not yet in the response body)

- [ ] **Step 3: Update `_serialize_alert` in `backend/app/routers/alerts.py`**

```python
from app.pipeline import _decode_json_list, decode_key_points
```

Replace the existing `from app.pipeline import decode_key_points` import line with the one above.

```python
def _serialize_alert(
    alert: Alert,
    held_company_ids: set[int],
    article_titles: dict[int, str],
    ac_translations: dict[int, tuple[str, list[str]]],
    category_labels: dict[str, str],
    mentions_index,
) -> dict:
    companies = []
    for ac in alert.companies:
        rationale, key_points = ac_translations.get(ac.id, (ac.rationale, decode_key_points(ac)))
        companies.append({
            "company_id": ac.company_id, "ticker": ac.company.ticker, "name": ac.company.name,
            "index_tier": ac.company.index_tier, "sector": ac.company.sector, "direction": ac.direction,
            "magnitude_low": ac.magnitude_low, "magnitude_high": ac.magnitude_high,
            "rationale": rationale, "key_points": key_points,
            "confidence_score": ac.confidence_score, "time_horizon": ac.time_horizon,
            "basis": ac.basis, "confidence": ac.confidence,
            "confidence_band": ac.confidence_band,
            "reasons": _decode_json_list(ac.reasons_json),
            "evidence_refs": _decode_json_list(ac.evidence_refs_json),
            "risks": _decode_json_list(ac.risks_json),
            "assumptions": _decode_json_list(ac.assumptions_json),
            "unknowns": _decode_json_list(ac.unknowns_json),
            "alternative_hypothesis": ac.alternative_hypothesis,
            "market": infer_market(ac.company.ticker),
            "in_my_holdings": ac.company_id in held_company_ids,
            "past_mentions": mentions_before(mentions_index, ac.company_id, alert.created_at),
        })
    return {
        "id": alert.id,
        "category": alert.category,
        "category_label": category_labels.get(alert.category, alert.category),
        "event_type": alert.event_type,
        "created_at": alert.created_at.isoformat(),
        "article": {
            "id": alert.article.id,
            "title": article_titles.get(alert.article_id, alert.article.title),
            "url": alert.article.url,
            "image_url": alert.article.image_url,
        },
        "companies": companies,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_api.py -v`
Expected: PASS (all tests, including pre-existing ones — every new response field is additive)

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/alerts.py backend/tests/test_api.py
git commit -m "feat: expose reasoning engine fields via the alerts API"
```

---

## Explicitly out of scope for this plan

Frontend changes (splitting the rationale display into Facts/Evidence/Reasoning/Risks sections, extending `ConfidenceTree`) — separate, focused frontend design once this backend shape has shipped and is stable. Knowledge graph, vector DB/RAG, task queues, manual company knowledge base, prompt-registry service, full evaluation suite — all deferred per the design spec's "Explicitly deferred" section.
