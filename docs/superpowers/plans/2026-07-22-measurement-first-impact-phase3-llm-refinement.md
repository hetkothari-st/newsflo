# Measurement-First Impact Architecture — Phase 3 (LLM Refinement Layer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repoint the existing LLM cascade at explanation, never numbers. Add plain-language `summary_short`/`summary_long` (event-level), a `why` causal-link field written **against the already-measured** `excess_move_pct` (never predicting it), a mapping from the existing `ImpactEdge.relation` vocabulary onto the spec's `RippleLink.relationship` enum, per-horizon `TimelineEffect` rows, company `business_desc`/`supply_chain` enrichment, a derived `peers` lookup, and an automated compliance guard that rejects any LLM output containing a percentage, price target, or buy/sell/hold language — exactly as specified in `docs/NEWS_IMPACT_APP_SPEC.md` §3.1, §5.2, §7, §10 and the task brief's Phase 3 (`C:\Users\ST269\Downloads\CLAUDE_TASK_measurement_first_impact.md`).

**Architecture:** This phase builds on the measurement spine from Phase 1+2 (`docs/superpowers/plans/2026-07-22-measurement-first-impact-phase1-2.md`, already shipped — `MarketMove` rows exist per (alert, company) with `excess_move_pct`/`measurement_status`). Every new LLM call here is additive: new modules, new nullable columns, one new table, one new optional parameter on the existing `_persist_alert`. Nothing existing is deleted, renamed, or made to behave differently when this phase's new `client` parameter is omitted. This phase is entirely backend, zero UI change — nothing built here is rendered yet (that's Phase 4+, a separate plan).

**Tech Stack:** Same as Phase 1+2 — FastAPI + SQLAlchemy (no Alembic — manual `_ADDED_COLUMNS`/`create_all`), SQLite (dev) / Postgres (prod), the existing OpenAI-compatible LLM client shim (`app/analysis/claude_client.py` — `MODEL`/`FALLBACK_MODEL`/`SYSTEM_PROMPT`, tool-calling via `client.chat.completions.create(tools=[...], tool_choice=...)`), `pytest`.

**Prerequisite — branch base:** Phase 1+2 shipped on `worktree-measurement-first-impact-phase1-2` (11 commits, base `196cfb1..a9b44d8`) but was **kept as-is, not merged to master**, per the user's choice at the end of that phase. This plan's Task 9 imports `measure_company_move` and appends to `_persist_alert`'s already-modified `MarketMove`-collecting loop — code that exists ONLY on that branch. **Any new isolated workspace for this plan must branch from `worktree-measurement-first-impact-phase1-2` (or from master only after that branch has been merged into it), never from a fresh `origin/master`** — a default "fresh" worktree would silently be missing all of Phase 1+2's code and every task from Task 3 onward would fail to import `MarketMove`/`measure_company_move`. Verify `git log --oneline -5` shows `a9b44d8` (or later) in the workspace's history before starting Task 1.

## Global Constraints

- **Never delete existing code.** Every change in this plan is additive: new modules, new nullable columns with safe defaults, one new optional parameter (`client=None`) that preserves every existing call site's current behavior unchanged. If a step ever seems to require removing/altering existing behavior, comment it out with a note instead and flag it — per explicit user instruction for this whole task.
- **No LLM-generated number reaches a user.** Every text field this phase produces (`summary_short`, `summary_long`, `why`, `TimelineEffect.description`, `business_desc`) must pass `validate_no_advice_language` before being persisted. A percentage figure, a price-target phrase, or buy/sell/hold/rating language anywhere in the text is rejected.
- **`why` is written against the measured move, never predicts it.** The prompt receives the company's real `excess_move_pct` (already computed by Phase 1's `measure_company_move`) as *context* for framing (a "sharp" vs. "modest" reaction), but the generated text must never restate, estimate, or imply any percentage/price itself — the number is shown separately, already measured.
- **A company with no real measured move gets no fabricated `why`.** `generate_impact_whys` is only ever called with companies whose `MarketMove.measurement_status == "ok"`. A ripple-linked company with `no_data`/`stale`/no measurement gets `AlertCompany.why = None` — never a fabricated causal story dressed up as impact. This is what `is_exposure_only()` (Task 2) exists to let a later UI phase label correctly ("exposure," not "impact").
- **Reject-and-regenerate, then drop — never persist rejected text.** Every generation function retries once (a fresh call) for any field/entry that fails validation; if still invalid after the retry, that field/entry is dropped (set to `None`/omitted from the result), never persisted as-is.
- **Ripple relationship mapping (`ImpactEdge.relation` → spec's `RippleLink.relationship` enum) is pure — no LLM call, no new column.** It's a read-time relabeling function; `ImpactEdge.source` (`rulebook_verified`/`rulebook_pruned`/`llm_only`) provenance is untouched.
- **`Stock.peers` is derived, never persisted as a stored array** — a deliberate, documented deviation from the spec's literal data model (see Task 8's docstring). Peers are 100% derivable from `Company.sector` at read time; storing them would be a denormalized cache that goes stale with no independent value, the same "derived, never persisted as truth" discipline this architecture already applies to `intensity`/`cap_tier` (Phase 2). Flagged in this plan's STOP report for confirmation, not silently assumed.
- New DB table (`TimelineEffect`) → model class only, no `_ADDED_COLUMNS` entry. New columns on existing tables (`Alert`, `AlertCompany`, `Company`) → **do** need `_ADDED_COLUMNS` entries, all nullable, no default that could look like a real value.
- Don't delete/weaken the existing cascade (`app/analysis/cascade.py`), rulebook, confidence engine, or `ImpactEdge` — this plan adds new modules alongside them, touching `app/pipeline.py` only at one precisely-scoped insertion point (Task 9).
- Don't weaken or delete existing tests to make something pass. The existing `~35`-test-strong pipeline suite must keep passing unchanged — the new `client=None` default and a new autouse conftest stub (Task 9) guarantee this.
- Full backend test suite must pass with zero regressions at the end (Task 10).
- If a spec instruction genuinely conflicts with existing code or architecture, STOP and report rather than guessing — see the `peers`-as-derived deviation above as the one place this plan makes that call explicitly rather than blocking.

---

## File Structure

```
backend/app/reasoning/compliance.py           NEW — validate_no_advice_language, validate_or_none
backend/app/reasoning/ripple_relationship.py  NEW — relation_to_ripple_relationship, is_exposure_only
backend/app/analysis/refinement.py            NEW — generate_event_summary, generate_impact_whys,
                                               generate_timeline_effects, refine_alert (built up across
                                               Tasks 4/5/6/9)
backend/app/companies/business_profile.py     NEW — generate_business_profiles_batch
backend/app/companies/peers.py                NEW — get_sector_peers
backend/backfill_business_profiles.py         NEW — one-time enrichment script (mirrors backfill_subsectors.py)

backend/app/models.py                         MODIFY — Alert.summary_short/summary_long,
                                               AlertCompany.why, Company.business_desc/
                                               supply_chain_suppliers_json/supply_chain_customers_json,
                                               new TimelineEffect class
backend/app/db.py                             MODIFY — 6 new _ADDED_COLUMNS entries
backend/app/pipeline.py                       MODIFY — _persist_alert gains client=None param,
                                               collects alert_companies/market_moves lists,
                                               calls refine_alert when client is provided
backend/tests/conftest.py                     MODIFY — autouse stub for refine_alert

backend/tests/test_compliance.py              NEW
backend/tests/test_ripple_relationship.py     NEW
backend/tests/test_refinement.py              NEW (built up across Tasks 4/5/6/9)
backend/tests/test_business_profile.py        NEW
backend/tests/test_peers.py                   NEW
backend/tests/test_refine_alert_wiring.py     NEW
```

---

## Task 1: Compliance guard (output validation)

**Files:**
- Create: `backend/app/reasoning/compliance.py`
- Test: `backend/tests/test_compliance.py`

**Interfaces:**
- Produces: `ValidationResult(is_valid: bool, reason: str | None)` (NamedTuple), `validate_no_advice_language(text: str) -> ValidationResult`, `validate_or_none(text: str | None) -> str | None`. Consumed by every generation function in Tasks 4-7.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_compliance.py`:

```python
from app.reasoning.compliance import validate_no_advice_language, validate_or_none


def test_rejects_percentage_figure():
    result = validate_no_advice_language("Analysts expect ~5% upside from here")
    assert result.is_valid is False
    assert "percentage" in result.reason


def test_rejects_negative_percentage_figure():
    result = validate_no_advice_language("The stock could see -3.5% downside")
    assert result.is_valid is False


def test_rejects_price_target_phrase():
    result = validate_no_advice_language("We set a price target of 500 for this stock")
    assert result.is_valid is False
    assert "price-target" in result.reason


def test_rejects_target_price_word_order_too():
    result = validate_no_advice_language("Our target price is under review")
    assert result.is_valid is False


def test_rejects_buy_sell_hold_language():
    for word in ["buy", "sell", "hold", "overweight", "underweight"]:
        result = validate_no_advice_language(f"We recommend investors {word} this stock")
        assert result.is_valid is False, f"{word!r} should have been rejected"


def test_accepts_clean_causal_text():
    result = validate_no_advice_language(
        "A weaker rupee raises the value of this company's dollar-denominated export revenue."
    )
    assert result.is_valid is True
    assert result.reason is None


def test_accepts_empty_or_none_text():
    assert validate_no_advice_language("").is_valid is True
    assert validate_no_advice_language(None).is_valid is True


def test_validate_or_none_returns_text_when_valid():
    text = "A rate cut lowers borrowing costs for this lender's customers."
    assert validate_or_none(text) == text


def test_validate_or_none_returns_none_when_invalid():
    assert validate_or_none("Expect ~5% upside") is None


def test_validate_or_none_passes_through_none():
    assert validate_or_none(None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_compliance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reasoning.compliance'`.

- [ ] **Step 3: Implement**

Create `backend/app/reasoning/compliance.py`:

```python
"""Compliance guard: reject any LLM-generated text containing a
percentage, price target, or buy/sell/hold-style language before it is
ever persisted (docs/NEWS_IMPACT_APP_SPEC.md §7, §10 -- "No LLM-generated
number reaches a user"). Every LLM refinement function in
app.analysis.refinement and app.companies.business_profile runs its
generated text through this before persisting it.
"""
import re
from typing import NamedTuple

_PERCENT_RE = re.compile(r"-?\d+(\.\d+)?\s*%")
_TARGET_PRICE_RE = re.compile(r"\btarget\s+price\b|\bprice\s+target\b", re.IGNORECASE)
_ADVICE_WORDS_RE = re.compile(
    r"\b(buy|sell|hold|overweight|underweight|outperform|underperform)\b", re.IGNORECASE
)


class ValidationResult(NamedTuple):
    is_valid: bool
    reason: str | None


def validate_no_advice_language(text: str | None) -> ValidationResult:
    """Rejects text containing a percentage figure, a price-target phrase,
    or buy/sell/hold/rating language -- the three categories this
    architecture never allows an LLM to emit (measured numbers only, no
    advice). Empty/None text is valid (nothing to reject)."""
    if not text:
        return ValidationResult(True, None)
    if _PERCENT_RE.search(text):
        return ValidationResult(False, "contains a percentage figure")
    if _TARGET_PRICE_RE.search(text):
        return ValidationResult(False, "contains a price-target phrase")
    match = _ADVICE_WORDS_RE.search(text)
    if match:
        return ValidationResult(False, f"contains buy/sell/hold-style language ({match.group(0)!r})")
    return ValidationResult(True, None)


def validate_or_none(text: str | None) -> str | None:
    """Convenience wrapper for generation call sites: returns ``text``
    unchanged if it passes validate_no_advice_language, else None -- so a
    caller can always do ``field = validate_or_none(llm_output)`` and never
    persist rejected text."""
    if text is None:
        return None
    return text if validate_no_advice_language(text).is_valid else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_compliance.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/compliance.py backend/tests/test_compliance.py
git commit -m "feat: add compliance guard rejecting percentage/price-target/buy-sell-hold language"
```

---

## Task 2: Ripple relationship mapping

**Files:**
- Create: `backend/app/reasoning/ripple_relationship.py`
- Test: `backend/tests/test_ripple_relationship.py`

**Interfaces:**
- Consumes: `app.reasoning.rulebook.EDGE_RELATIONS` (the existing 10-value `ImpactEdge.relation` vocabulary).
- Produces: `RIPPLE_RELATIONSHIPS: list[str]` (the spec's 6-value enum), `relation_to_ripple_relationship(relation: str) -> str`, `is_exposure_only(measurement_status: str | None) -> bool`. Consumed by a later UI phase (Phase 6), not wired anywhere in this plan.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_ripple_relationship.py`:

```python
from app.reasoning.rulebook import EDGE_RELATIONS
from app.reasoning.ripple_relationship import (
    RIPPLE_RELATIONSHIPS,
    is_exposure_only,
    relation_to_ripple_relationship,
)


def test_every_edge_relation_maps_to_a_valid_ripple_relationship():
    for relation in EDGE_RELATIONS:
        mapped = relation_to_ripple_relationship(relation)
        assert mapped in RIPPLE_RELATIONSHIPS, f"{relation!r} mapped to invalid {mapped!r}"


def test_supplier_maps_to_supplier():
    assert relation_to_ripple_relationship("supplier") == "SUPPLIER"


def test_competitor_maps_to_competitor():
    assert relation_to_ripple_relationship("competitor") == "COMPETITOR"


def test_unrecognized_relation_falls_back_to_sector_wide():
    assert relation_to_ripple_relationship("not_a_real_relation") == "SECTOR_WIDE"


def test_is_exposure_only_true_for_no_data_and_stale_and_none():
    assert is_exposure_only("no_data") is True
    assert is_exposure_only("stale") is True
    assert is_exposure_only(None) is True


def test_is_exposure_only_false_for_ok():
    assert is_exposure_only("ok") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_ripple_relationship.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reasoning.ripple_relationship'`.

- [ ] **Step 3: Implement**

Create `backend/app/reasoning/ripple_relationship.py`:

```python
"""Maps app.reasoning.rulebook.EDGE_RELATIONS (this codebase's existing
ImpactEdge.relation vocabulary) onto docs/NEWS_IMPACT_APP_SPEC.md's
RippleLink.relationship enum (spec §3.1) -- pure, no LLM call. Keeps every
edge's existing `source` provenance (rulebook_verified / rulebook_pruned /
llm_only) untouched; this is a read-time relabeling only, applied by a
later UI phase's grouping logic, never by rewriting ImpactEdge rows.
"""

RIPPLE_RELATIONSHIPS = [
    "BENEFICIARY", "CUSTOMER_INPUT_COST", "SUPPLIER", "SUBSTITUTE", "COMPETITOR", "SECTOR_WIDE",
]

# Documented, deterministic many-to-one mapping -- EDGE_RELATIONS has 10
# finer-grained values, the spec's RippleLink.relationship has 6 coarser
# ones, so this is necessarily lossy. Each choice below is a defensible
# reading of the existing relation's typical usage in
# app.reasoning.rulebook.CHAINS, not a claim of perfect semantic identity.
# SUBSTITUTE has no forward mapping (no existing relation genuinely means
# "alternative/replacement product") -- that's fine, the spec only
# requires every SOURCE value to map somewhere, not every target value to
# be reachable.
_RELATION_TO_RIPPLE_RELATIONSHIP: dict[str, str] = {
    "supplier": "SUPPLIER",
    "customer": "CUSTOMER_INPUT_COST",
    "input_cost": "CUSTOMER_INPUT_COST",
    "competitor": "COMPETITOR",
    "commodity": "BENEFICIARY",
    "demand": "BENEFICIARY",
    "credit_cost": "SECTOR_WIDE",
    "regulation": "SECTOR_WIDE",
    "currency": "SECTOR_WIDE",
    "correlation": "SECTOR_WIDE",
}


def relation_to_ripple_relationship(relation: str) -> str:
    """Maps a known ImpactEdge.relation value to the spec's RippleLink
    enum. An unrecognized relation (should not happen -- EDGE_RELATIONS is
    a closed, enum-constrained vocabulary at the LLM tool-schema layer --
    but defended here anyway) falls back to SECTOR_WIDE, the most
    conservative/general bucket, rather than raising."""
    return _RELATION_TO_RIPPLE_RELATIONSHIP.get(relation, "SECTOR_WIDE")


def is_exposure_only(measurement_status: str | None) -> bool:
    """True when a ripple-linked company has no real measured move
    (measurement_status is None, 'no_data', or 'stale') -- a later UI
    phase must label this as a flagged EXPOSURE, never an impact, and must
    never render a number/score for it (spec: "ripple companies that have
    not moved... show it as a flagged relationship with no number and no
    score -- never a fabricated magnitude")."""
    return measurement_status != "ok"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_ripple_relationship.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/ripple_relationship.py backend/tests/test_ripple_relationship.py
git commit -m "feat: map ImpactEdge.relation onto spec's RippleLink.relationship enum"
```

---

## Task 3: New model fields + `TimelineEffect` table

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/db.py`

**Interfaces:**
- Produces: `Alert.summary_short`, `Alert.summary_long`, `AlertCompany.why`, `Company.business_desc`, `Company.supply_chain_suppliers_json`, `Company.supply_chain_customers_json`, and the `TimelineEffect` model (`id, alert_id, horizon, description, created_at`). Consumed by Tasks 4-9.

- [ ] **Step 1: Add the new columns to existing models**

In `backend/app/models.py`, in the `Alert` class, add these two lines directly after the existing `knowledge_version = Column(String, nullable=True)` line:

```python
    # LLM-generated, plain-language event summary (spec §5.2) -- populated
    # post-persist by app.analysis.refinement.refine_alert, never by the
    # cascade stages that produce per-company rationale/magnitude.
    summary_short = Column(String, nullable=True)  # <= 12 words, the one-line "why"
    summary_long = Column(Text, nullable=True)  # 2 sentences, plain language
```

In the `AlertCompany` class, add this line directly after the existing `parent_company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)` line:

```python
    # The causal link written AGAINST the already-measured excess_move_pct
    # (see app.market.measure.MarketMove) -- never a prediction. Populated
    # only for companies with measurement_status == "ok"; NULL for a
    # ripple company with no real measured move (never fabricated).
    why = Column(Text, nullable=True)
```

In the `Company` class, add these three lines directly after the existing `instrument_token = Column(Integer, nullable=True)` line:

```python
    # Plain-language "what they do" for the (i) button, plus supply-chain
    # suppliers/customers (spec §3.1) -- one-time LLM enrichment, see
    # backend/backfill_business_profiles.py. NULL until enriched.
    business_desc = Column(Text, nullable=True)
    supply_chain_suppliers_json = Column(Text, nullable=True)  # JSON-encoded list[str]
    supply_chain_customers_json = Column(Text, nullable=True)  # JSON-encoded list[str]
```

- [ ] **Step 2: Add the `TimelineEffect` model**

Append to `backend/app/models.py`, after the `MarketMove` class:

```python
class TimelineEffect(Base):
    """One row per (alert, horizon) -- how the event's effect unfolds over
    time (docs/NEWS_IMPACT_APP_SPEC.md §3.1, §4 Level 3). Only horizons the
    LLM refinement layer found genuine, distinct content for get a row --
    zero, one, or several rows per alert, never a fixed five. Populated by
    app.analysis.refinement.refine_alert, same call as Alert.summary_short/
    summary_long and AlertCompany.why.
    """
    __tablename__ = "timeline_effects"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    horizon = Column(String, nullable=False)  # TODAY | DAYS | WEEKS | MONTHS | QUARTERS
    description = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    alert = relationship("Alert")
```

- [ ] **Step 3: Register the new columns in `_ADDED_COLUMNS`**

In `backend/app/db.py`, append to the `_ADDED_COLUMNS` list (after its last existing entry, `("articles", "full_content_fetch_attempted_at", "TIMESTAMP")`):

```python
    ("alerts", "summary_short", "VARCHAR"),
    ("alerts", "summary_long", "TEXT"),
    ("alert_companies", "why", "TEXT"),
    ("companies", "business_desc", "TEXT"),
    ("companies", "supply_chain_suppliers_json", "TEXT"),
    ("companies", "supply_chain_customers_json", "TEXT"),
```

- [ ] **Step 4: Verify existing tests still pass**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: all PASS (new nullable columns + new table, nothing existing changes shape).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/db.py
git commit -m "feat: add summary/why/business_desc/supply_chain columns and TimelineEffect table"
```

---

## Task 4: Event summary generation

**Files:**
- Create/modify: `backend/app/analysis/refinement.py` (new file, first function)
- Test: `backend/tests/test_refinement.py` (new file, first section)

**Interfaces:**
- Consumes: `app.analysis.claude_client.MODEL`/`FALLBACK_MODEL`/`SYSTEM_PROMPT`, `app.reasoning.compliance.validate_or_none`.
- Produces: `generate_event_summary(client, title: str, content: str) -> dict | None` returning `{"summary_short": str | None, "summary_long": str | None}` or `None` if nothing usable survives validation. Consumed by `refine_alert` (Task 9).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_refinement.py`:

```python
import json
from types import SimpleNamespace

from app.analysis.refinement import generate_event_summary


class FakeToolCall:
    def __init__(self, name, arguments_dict):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments_dict))


class QueuedFakeClient:
    """Returns queued responses in order, one per call to
    chat.completions.create -- lets a test script a first response and a
    distinct retry response, matching the reject-and-regenerate-once
    pattern every generation function in this module follows. Raises
    AssertionError if more calls happen than responses were queued."""

    def __init__(self, responses: list[tuple[str, dict]]):
        # each item: (tool_name, arguments_dict)
        self._responses = list(responses)
        self.calls = 0

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            if not self._outer._responses:
                raise AssertionError("QueuedFakeClient: no more responses queued")
            self._outer.calls += 1
            name, arguments = self._outer._responses.pop(0)
            message = SimpleNamespace(tool_calls=[FakeToolCall(name, arguments)])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    @property
    def chat(self):
        return SimpleNamespace(completions=self._Completions(self))


def test_generate_event_summary_returns_valid_fields():
    client = QueuedFakeClient([
        ("record_event_summary", {
            "summary_short": "RBI cuts repo rate by 25 basis points",
            "summary_long": "The RBI lowered its key lending rate. This should ease borrowing costs across the economy.",
        }),
    ])
    result = generate_event_summary(client, "RBI cuts rates", "The RBI cut the repo rate today.")
    assert result["summary_short"] == "RBI cuts repo rate by 25 basis points"
    assert "ease borrowing costs" in result["summary_long"]
    assert client.calls == 1


def test_generate_event_summary_retries_once_on_invalid_text_then_uses_retry():
    client = QueuedFakeClient([
        ("record_event_summary", {
            "summary_short": "Stock could see ~5% upside",  # rejected: percentage
            "summary_long": "A clean two sentence summary. No advice language here.",
        }),
        ("record_event_summary", {
            "summary_short": "News moves this company's outlook",
            "summary_long": "A clean two sentence summary retried. Still no advice language.",
        }),
    ])
    result = generate_event_summary(client, "t", "c")
    assert result["summary_short"] == "News moves this company's outlook"
    assert client.calls == 2


def test_generate_event_summary_returns_none_when_both_fields_invalid_even_after_retry():
    client = QueuedFakeClient([
        ("record_event_summary", {"summary_short": "Buy this stock now", "summary_long": "Sell before it drops 5%."}),
        ("record_event_summary", {"summary_short": "Buy more of this", "summary_long": "Hold for 5% gains."}),
    ])
    result = generate_event_summary(client, "t", "c")
    assert result is None
    assert client.calls == 2


def test_generate_event_summary_returns_none_when_no_tool_call():
    class NoToolCallClient:
        class _Completions:
            def create(self, **kwargs):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None))])

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions())

    assert generate_event_summary(NoToolCallClient(), "t", "c") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_refinement.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis.refinement'`.

- [ ] **Step 3: Implement**

Create `backend/app/analysis/refinement.py`:

```python
"""The LLM refinement layer (docs/NEWS_IMPACT_APP_SPEC.md, this repo's
docs/superpowers/plans/2026-07-22-measurement-first-impact-phase3-llm-
refinement.md). Every function here produces TEXT explaining an
already-measured fact -- never a number, never a prediction. Measurement
(app.market.measure) is the spine; this module is the explanation layer on
top of it. Built up across the plan's Tasks 4 (generate_event_summary), 5
(generate_impact_whys), 6 (generate_timeline_effects), and 9
(refine_alert, the orchestrator).
"""
import json

from openai import RateLimitError

from app.analysis.claude_client import FALLBACK_MODEL, MODEL, SYSTEM_PROMPT
from app.reasoning.compliance import validate_or_none

EVENT_SUMMARY_FRAMING = (
    "Summarize this news event for a retail investor with no finance "
    "background. summary_short must be 12 words or fewer -- the single "
    "most important, plain-language takeaway. summary_long must be "
    "exactly two sentences, plain language, no jargon (unpack any finance "
    "term you use). Do not include any percentage, price, price target, "
    "or buy/sell/hold language -- describe what happened and why it "
    "matters, not whether to trade on it."
)


def build_event_summary_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_event_summary",
            "description": "Summarize this news event in plain, jargon-free language.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary_short": {
                        "type": "string",
                        "description": "One line, 12 words or fewer, the core 'why this matters' in plain language.",
                    },
                    "summary_long": {
                        "type": "string",
                        "description": "Exactly two plain-language sentences, jargon-free, expanding on summary_short.",
                    },
                },
                "required": ["summary_short", "summary_long"],
            },
        },
    }


def _call_event_summary_tool(client, title: str, content: str) -> dict | None:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{EVENT_SUMMARY_FRAMING}\n\nTitle: {title}\n\nContent: {content}"},
    ]
    tool = build_event_summary_tool()
    try:
        response = client.chat.completions.create(
            model=MODEL, max_tokens=512, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_event_summary"}},
            messages=messages,
        )
    except RateLimitError:
        response = client.chat.completions.create(
            model=FALLBACK_MODEL, max_tokens=512, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_event_summary"}},
            messages=messages,
        )
    message = response.choices[0].message
    tool_call = next((tc for tc in (message.tool_calls or []) if tc.function.name == "record_event_summary"), None)
    if tool_call is None:
        return None
    return json.loads(tool_call.function.arguments)


def generate_event_summary(client, title: str, content: str) -> dict | None:
    """Returns {"summary_short", "summary_long"} (either may be None if it
    never passed validation, even after one retry), or None entirely if
    NEITHER field ever became usable. Never raises -- a malformed or
    missing tool-call response degrades to None, same "never crash the
    alert" discipline as app.market.measure.measure_company_move."""
    first = _call_event_summary_tool(client, title, content)
    if first is None:
        return None

    summary_short = validate_or_none(first.get("summary_short"))
    summary_long = validate_or_none(first.get("summary_long"))

    if summary_short is None or summary_long is None:
        retry = _call_event_summary_tool(client, title, content)
        if retry is not None:
            summary_short = summary_short or validate_or_none(retry.get("summary_short"))
            summary_long = summary_long or validate_or_none(retry.get("summary_long"))

    if summary_short is None and summary_long is None:
        return None
    return {"summary_short": summary_short, "summary_long": summary_long}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_refinement.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/refinement.py backend/tests/test_refinement.py
git commit -m "feat: add generate_event_summary — plain-language summary_short/summary_long"
```

---

## Task 5: Impact-why batch generation

**Files:**
- Modify: `backend/app/analysis/refinement.py` (append)
- Modify: `backend/tests/test_refinement.py` (append)

**Interfaces:**
- Consumes: same as Task 4, plus a list of measured-company dicts.
- Produces: `generate_impact_whys(client, title: str, content: str, companies: list[dict]) -> dict[str, str]` where each input dict is `{"ticker", "name", "direction", "excess_move_pct"}` (only companies with a real measured excess should ever be passed in — see Task 9). Returns `{ticker: why_text}` — a ticker omitted by the model, or whose text is never validated even after retry, is absent from the result. Consumed by `refine_alert` (Task 9).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_refinement.py`:

```python
from app.analysis.refinement import generate_impact_whys


def _measured_companies():
    return [
        {"ticker": "RELIANCE.NS", "name": "Reliance Industries", "direction": "bullish", "excess_move_pct": 3.2},
        {"ticker": "ONGC.NS", "name": "ONGC", "direction": "bearish", "excess_move_pct": -1.1},
    ]


def test_generate_impact_whys_returns_valid_texts_per_ticker():
    client = QueuedFakeClient([
        ("record_impact_whys", {"whys": [
            {"ticker": "RELIANCE.NS", "why": "Higher crude prices lift refining margins for this company."},
            {"ticker": "ONGC.NS", "why": "A weaker rupee raises this importer's input costs."},
        ]}),
    ])
    result = generate_impact_whys(client, "t", "c", _measured_companies())
    assert result["RELIANCE.NS"] == "Higher crude prices lift refining margins for this company."
    assert result["ONGC.NS"] == "A weaker rupee raises this importer's input costs."
    assert client.calls == 1


def test_generate_impact_whys_retries_only_the_rejected_tickers():
    client = QueuedFakeClient([
        ("record_impact_whys", {"whys": [
            {"ticker": "RELIANCE.NS", "why": "Expect ~5% upside from refining margins."},  # rejected
            {"ticker": "ONGC.NS", "why": "A weaker rupee raises this importer's input costs."},  # valid
        ]}),
        ("record_impact_whys", {"whys": [
            {"ticker": "RELIANCE.NS", "why": "Higher crude prices lift refining margins for this company."},
        ]}),
    ])
    result = generate_impact_whys(client, "t", "c", _measured_companies())
    assert result["RELIANCE.NS"] == "Higher crude prices lift refining margins for this company."
    assert result["ONGC.NS"] == "A weaker rupee raises this importer's input costs."
    assert client.calls == 2


def test_generate_impact_whys_drops_ticker_still_invalid_after_retry():
    client = QueuedFakeClient([
        ("record_impact_whys", {"whys": [
            {"ticker": "RELIANCE.NS", "why": "Buy this stock, expect 5% upside."},
        ]}),
        ("record_impact_whys", {"whys": [
            {"ticker": "RELIANCE.NS", "why": "Sell before the 5% drop."},
        ]}),
    ])
    result = generate_impact_whys(client, "t", "c", [_measured_companies()[0]])
    assert "RELIANCE.NS" not in result
    assert client.calls == 2


def test_generate_impact_whys_ticker_the_model_never_answers_is_not_retried():
    client = QueuedFakeClient([
        ("record_impact_whys", {"whys": []}),  # model answered nothing
    ])
    result = generate_impact_whys(client, "t", "c", [_measured_companies()[0]])
    assert result == {}
    assert client.calls == 1  # no retry -- ticker was never produced, not rejected


def test_generate_impact_whys_returns_empty_dict_for_no_companies():
    assert generate_impact_whys(QueuedFakeClient([]), "t", "c", []) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_refinement.py -v -k impact_whys`
Expected: FAIL with `ImportError: cannot import name 'generate_impact_whys'`.

- [ ] **Step 3: Implement**

Append to `backend/app/analysis/refinement.py`:

```python
IMPACT_WHY_FRAMING = (
    "Each company below already has a MEASURED market reaction to this "
    "news -- a real, observed price move relative to its sector, already "
    "computed from market data. Your job is ONLY to explain, in one "
    "plain-language sentence per company, the causal mechanism: why this "
    "specific news would move this specific company in that direction. "
    "You are explaining an observed fact, not predicting one -- never "
    "restate, estimate, or imply any percentage, price, or magnitude in "
    "your explanation; the number itself is already measured and shown "
    "separately. Never use buy/sell/hold, rating, or price-target "
    "language. If you cannot state a genuine, specific mechanism for a "
    "company, omit it rather than writing a vague sentence."
)


def build_impact_why_tool(tickers: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_impact_whys",
            "description": "Explain, in plain language, why each company's already-measured market reaction happened.",
            "parameters": {
                "type": "object",
                "properties": {
                    "whys": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ticker": {"type": "string", "enum": tickers},
                                "why": {"type": "string"},
                            },
                            "required": ["ticker", "why"],
                        },
                    },
                },
                "required": ["whys"],
            },
        },
    }


def _call_impact_why_tool(client, title: str, content: str, companies: list[dict]) -> dict[str, str]:
    tickers = [c["ticker"] for c in companies]
    company_lines = "\n".join(
        f"- {c['ticker']} ({c['name']}): moved {c['direction']}, a "
        f"{'sharp' if abs(c['excess_move_pct']) >= 3 else 'modest'} reaction "
        "relative to its sector (do not restate any number in your answer)"
        for c in companies
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"{IMPACT_WHY_FRAMING}\n\nArticle: {title}\n\n{content}\n\nCompanies:\n{company_lines}",
        },
    ]
    tool = build_impact_why_tool(tickers)
    try:
        response = client.chat.completions.create(
            model=MODEL, max_tokens=2048, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_impact_whys"}},
            messages=messages,
        )
    except RateLimitError:
        response = client.chat.completions.create(
            model=FALLBACK_MODEL, max_tokens=2048, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_impact_whys"}},
            messages=messages,
        )
    message = response.choices[0].message
    tool_call = next((tc for tc in (message.tool_calls or []) if tc.function.name == "record_impact_whys"), None)
    if tool_call is None:
        return {}
    arguments = json.loads(tool_call.function.arguments)
    return {
        entry["ticker"]: entry["why"] for entry in arguments.get("whys", [])
        if entry.get("ticker") and entry.get("why")
    }


def generate_impact_whys(client, title: str, content: str, companies: list[dict]) -> dict[str, str]:
    """companies: [{"ticker", "name", "direction", "excess_move_pct"}, ...]
    -- only companies with a real measured excess_move_pct
    (measurement_status == "ok") should ever be passed in; this function
    never invents a why for a company with no measured move. Returns
    {ticker: why} -- a ticker the model never answered is not retried
    (same "omit rather than mismatch" discipline as
    app.companies.sub_sectors.classify_batch); a ticker the model DID
    answer but whose text fails validation gets one batched retry
    covering every such ticker, then is dropped if still invalid.
    """
    if not companies:
        return {}
    tickers = [c["ticker"] for c in companies]
    first = _call_impact_why_tool(client, title, content, companies)

    result: dict[str, str] = {}
    retry_tickers = []
    for ticker in tickers:
        if ticker not in first:
            continue  # model never answered -- not retried, simply absent
        text = validate_or_none(first[ticker])
        if text is not None:
            result[ticker] = text
        else:
            retry_tickers.append(ticker)

    if retry_tickers:
        retry_companies = [c for c in companies if c["ticker"] in retry_tickers]
        retry = _call_impact_why_tool(client, title, content, retry_companies)
        for ticker in retry_tickers:
            text = validate_or_none(retry.get(ticker))
            if text is not None:
                result[ticker] = text

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_refinement.py -v`
Expected: all PASS (Task 4's tests still pass too).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/refinement.py backend/tests/test_refinement.py
git commit -m "feat: add generate_impact_whys — batch causal-link text against measured excess move"
```

---

## Task 6: Timeline effects generation

**Files:**
- Modify: `backend/app/analysis/refinement.py` (append)
- Modify: `backend/tests/test_refinement.py` (append)

**Interfaces:**
- Produces: `HORIZONS: list[str]` (`TODAY, DAYS, WEEKS, MONTHS, QUARTERS`), `generate_timeline_effects(client, title: str, content: str) -> list[dict]` returning `[{"horizon", "description"}, ...]`, zero or more. Consumed by `refine_alert` (Task 9).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_refinement.py`:

```python
from app.analysis.refinement import HORIZONS, generate_timeline_effects


def test_generate_timeline_effects_returns_valid_entries():
    client = QueuedFakeClient([
        ("record_timeline_effects", {"effects": [
            {"horizon": "TODAY", "description": "Markets react immediately to the rate decision."},
            {"horizon": "QUARTERS", "description": "Lower rates gradually filter through to loan demand over time."},
        ]}),
    ])
    result = generate_timeline_effects(client, "t", "c")
    assert result == [
        {"horizon": "TODAY", "description": "Markets react immediately to the rate decision."},
        {"horizon": "QUARTERS", "description": "Lower rates gradually filter through to loan demand over time."},
    ]
    assert client.calls == 1


def test_generate_timeline_effects_can_return_zero_entries():
    client = QueuedFakeClient([("record_timeline_effects", {"effects": []})])
    assert generate_timeline_effects(client, "t", "c") == []


def test_generate_timeline_effects_drops_unrecognized_horizon():
    client = QueuedFakeClient([
        ("record_timeline_effects", {"effects": [
            {"horizon": "NEXT_WEEK", "description": "Not a real horizon value."},
            {"horizon": "DAYS", "description": "A genuine short-term effect description here."},
        ]}),
    ])
    result = generate_timeline_effects(client, "t", "c")
    assert result == [{"horizon": "DAYS", "description": "A genuine short-term effect description here."}]


def test_generate_timeline_effects_retries_only_invalid_horizons():
    client = QueuedFakeClient([
        ("record_timeline_effects", {"effects": [
            {"horizon": "TODAY", "description": "Expect ~5% move today."},  # rejected
            {"horizon": "WEEKS", "description": "A genuine weeks-long effect plays out here."},  # valid
        ]}),
        ("record_timeline_effects", {"effects": [
            {"horizon": "TODAY", "description": "Markets react immediately to the news."},
        ]}),
    ])
    result = generate_timeline_effects(client, "t", "c")
    assert {"horizon": "TODAY", "description": "Markets react immediately to the news."} in result
    assert {"horizon": "WEEKS", "description": "A genuine weeks-long effect plays out here."} in result
    assert client.calls == 2


def test_all_five_horizon_values_are_recognized():
    assert HORIZONS == ["TODAY", "DAYS", "WEEKS", "MONTHS", "QUARTERS"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_refinement.py -v -k timeline`
Expected: FAIL with `ImportError: cannot import name 'generate_timeline_effects'`.

- [ ] **Step 3: Implement**

Append to `backend/app/analysis/refinement.py`:

```python
HORIZONS = ["TODAY", "DAYS", "WEEKS", "MONTHS", "QUARTERS"]

TIMELINE_FRAMING = (
    "Describe how this news event's effect plays out over time -- one "
    "entry per horizon that genuinely has something distinct to say "
    "(TODAY = immediate market reaction, DAYS = next few trading days, "
    "WEEKS = next few weeks, MONTHS = next few months, QUARTERS = "
    "multi-quarter/structural). Skip a horizon entirely if you have "
    "nothing genuinely distinct to add for it -- zero, one, or several "
    "entries are all correct depending on the story. Plain language, no "
    "jargon, no percentage, price, or buy/sell/hold language -- describe "
    "what unfolds, not whether to trade on it."
)


def build_timeline_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_timeline_effects",
            "description": "Describe how this news event's effect unfolds over time, one entry per relevant horizon.",
            "parameters": {
                "type": "object",
                "properties": {
                    "effects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "horizon": {"type": "string", "enum": HORIZONS},
                                "description": {"type": "string"},
                            },
                            "required": ["horizon", "description"],
                        },
                    },
                },
                "required": ["effects"],
            },
        },
    }


def _call_timeline_tool(client, title: str, content: str) -> list[dict]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{TIMELINE_FRAMING}\n\nTitle: {title}\n\nContent: {content}"},
    ]
    tool = build_timeline_tool()
    try:
        response = client.chat.completions.create(
            model=MODEL, max_tokens=1536, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_timeline_effects"}},
            messages=messages,
        )
    except RateLimitError:
        response = client.chat.completions.create(
            model=FALLBACK_MODEL, max_tokens=1536, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_timeline_effects"}},
            messages=messages,
        )
    message = response.choices[0].message
    tool_call = next((tc for tc in (message.tool_calls or []) if tc.function.name == "record_timeline_effects"), None)
    if tool_call is None:
        return []
    arguments = json.loads(tool_call.function.arguments)
    return [
        {"horizon": e["horizon"], "description": e["description"]}
        for e in arguments.get("effects", [])
        if e.get("horizon") in HORIZONS and e.get("description")
    ]


def generate_timeline_effects(client, title: str, content: str) -> list[dict]:
    """Returns [{"horizon", "description"}, ...], zero or more -- only for
    horizons the model gave genuine distinct content for AND whose
    description passes validation, retrying once (batched) for any
    horizon that failed validation, then dropping it if still invalid."""
    first = _call_timeline_tool(client, title, content)

    valid = []
    invalid_horizons = []
    for entry in first:
        text = validate_or_none(entry["description"])
        if text is not None:
            valid.append({"horizon": entry["horizon"], "description": text})
        else:
            invalid_horizons.append(entry["horizon"])

    if invalid_horizons:
        retry_by_horizon = {e["horizon"]: e["description"] for e in _call_timeline_tool(client, title, content)}
        for horizon in invalid_horizons:
            text = validate_or_none(retry_by_horizon.get(horizon))
            if text is not None:
                valid.append({"horizon": horizon, "description": text})

    return valid
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_refinement.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/refinement.py backend/tests/test_refinement.py
git commit -m "feat: add generate_timeline_effects — per-horizon effect descriptions"
```

---

## Task 7: Company business profile generation + backfill script

**Files:**
- Create: `backend/app/companies/business_profile.py`
- Create: `backend/backfill_business_profiles.py`
- Test: `backend/tests/test_business_profile.py`

**Interfaces:**
- Consumes: `app.analysis.claude_client.MODEL`/`FALLBACK_MODEL`/`SYSTEM_PROMPT`, `app.reasoning.compliance.validate_no_advice_language`.
- Produces: `generate_business_profiles_batch(client, companies: list[tuple[str, str, str]]) -> dict[str, dict]` where each input tuple is `(ticker, name, sector)`, returning `{ticker: {"business_desc", "suppliers", "customers"}}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_business_profile.py`:

```python
import json
from types import SimpleNamespace

from app.companies.business_profile import generate_business_profiles_batch


class FakeToolCall:
    def __init__(self, name, arguments_dict):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments_dict))


class QueuedFakeClient:
    def __init__(self, responses: list[tuple[str, dict]]):
        self._responses = list(responses)
        self.calls = 0

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            if not self._outer._responses:
                raise AssertionError("QueuedFakeClient: no more responses queued")
            self._outer.calls += 1
            name, arguments = self._outer._responses.pop(0)
            message = SimpleNamespace(tool_calls=[FakeToolCall(name, arguments)])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    @property
    def chat(self):
        return SimpleNamespace(completions=self._Completions(self))


def test_generate_business_profiles_batch_returns_valid_entries():
    client = QueuedFakeClient([
        ("record_business_profiles", {"profiles": [
            {
                "ticker": "RELIANCE.NS", "business_desc": "Runs oil refining, retail, and telecom businesses.",
                "suppliers": ["Crude oil producers"], "customers": ["Fuel retailers", "Telecom consumers"],
            },
        ]}),
    ])
    result = generate_business_profiles_batch(client, [("RELIANCE.NS", "Reliance Industries", "oil_gas")])
    assert result["RELIANCE.NS"]["business_desc"] == "Runs oil refining, retail, and telecom businesses."
    assert result["RELIANCE.NS"]["suppliers"] == ["Crude oil producers"]
    assert result["RELIANCE.NS"]["customers"] == ["Fuel retailers", "Telecom consumers"]
    assert client.calls == 1


def test_generate_business_profiles_batch_retries_only_rejected_tickers():
    client = QueuedFakeClient([
        ("record_business_profiles", {"profiles": [
            {"ticker": "A.NS", "business_desc": "Expect 5% growth this quarter.", "suppliers": [], "customers": []},
            {"ticker": "B.NS", "business_desc": "Makes steel products for construction.", "suppliers": ["Iron ore miners"], "customers": ["Builders"]},
        ]}),
        ("record_business_profiles", {"profiles": [
            {"ticker": "A.NS", "business_desc": "Manufactures consumer electronics.", "suppliers": ["Component makers"], "customers": ["Retailers"]},
        ]}),
    ])
    result = generate_business_profiles_batch(client, [
        ("A.NS", "Company A", "consumer_durables"), ("B.NS", "Company B", "metals"),
    ])
    assert result["A.NS"]["business_desc"] == "Manufactures consumer electronics."
    assert result["B.NS"]["business_desc"] == "Makes steel products for construction."
    assert client.calls == 2


def test_generate_business_profiles_batch_drops_ticker_still_invalid_after_retry():
    client = QueuedFakeClient([
        ("record_business_profiles", {"profiles": [
            {"ticker": "A.NS", "business_desc": "Buy this stock for 5% upside.", "suppliers": [], "customers": []},
        ]}),
        ("record_business_profiles", {"profiles": [
            {"ticker": "A.NS", "business_desc": "Sell before the price target hits.", "suppliers": [], "customers": []},
        ]}),
    ])
    result = generate_business_profiles_batch(client, [("A.NS", "Company A", "auto")])
    assert "A.NS" not in result
    assert client.calls == 2


def test_generate_business_profiles_batch_empty_for_no_companies():
    assert generate_business_profiles_batch(QueuedFakeClient([]), []) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_business_profile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.business_profile'`.

- [ ] **Step 3: Implement**

Create `backend/app/companies/business_profile.py`:

```python
"""LLM-assisted company enrichment: plain-language business description
plus supply-chain suppliers/customers, used for the (i) business/sector
popup and the discovery directory (docs/NEWS_IMPACT_APP_SPEC.md §3.1).
One-time-per-company enrichment job (see backend/backfill_business_
profiles.py) -- Company.business_desc/supply_chain_*_json are read at API-
serialization time, never written by the per-article analysis pipeline
(this is master company data, not per-event data), same pattern as
app.companies.sub_sectors.classify_batch / backfill_subsectors.py.
"""
import json

from openai import RateLimitError

from app.analysis.claude_client import FALLBACK_MODEL, MODEL, SYSTEM_PROMPT
from app.reasoning.compliance import validate_no_advice_language

BUSINESS_PROFILE_FRAMING = (
    "For each company below, write a one-sentence, jargon-free "
    "description of what it actually does (for a reader with no finance "
    "background), plus its main suppliers (companies/industries it buys "
    "key inputs from) and main customers (companies/industries it sells "
    "to) -- real, specific names or industries you actually know, not "
    "generic filler. Empty lists are correct when you don't have a "
    "confident, specific answer. No percentage, price, or buy/sell/hold "
    "language."
)


def build_business_profile_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_business_profiles",
            "description": "Describe each company's business in plain language and name its main suppliers/customers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "profiles": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ticker": {"type": "string"},
                                "business_desc": {"type": "string"},
                                "suppliers": {"type": "array", "items": {"type": "string"}},
                                "customers": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["ticker", "business_desc", "suppliers", "customers"],
                        },
                    },
                },
                "required": ["profiles"],
            },
        },
    }


def _call_business_profile_tool(client, companies: list[tuple[str, str, str]]) -> dict[str, dict]:
    listing = "\n".join(f"- {ticker}: {name} ({sector})" for ticker, name, sector in companies)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{BUSINESS_PROFILE_FRAMING}\n\nCompanies:\n{listing}"},
    ]
    tool = build_business_profile_tool()
    try:
        response = client.chat.completions.create(
            model=MODEL, max_tokens=4096, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_business_profiles"}},
            messages=messages,
        )
    except RateLimitError:
        response = client.chat.completions.create(
            model=FALLBACK_MODEL, max_tokens=4096, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_business_profiles"}},
            messages=messages,
        )
    message = response.choices[0].message
    tool_call = next((tc for tc in (message.tool_calls or []) if tc.function.name == "record_business_profiles"), None)
    if tool_call is None:
        return {}
    arguments = json.loads(tool_call.function.arguments)
    return {
        entry["ticker"]: entry for entry in arguments.get("profiles", [])
        if entry.get("ticker") and entry.get("business_desc")
    }


def generate_business_profiles_batch(client, companies: list[tuple[str, str, str]]) -> dict[str, dict]:
    """companies: [(ticker, name, sector), ...]. Returns {ticker: {
    business_desc, suppliers, customers}}. A ticker the model omits, or
    whose business_desc fails validate_no_advice_language even after one
    batched retry, is absent from the result -- the caller
    (backfill_business_profiles.py) leaves it unenriched and retries on
    the next run, same "omit rather than fabricate" discipline as
    app.companies.sub_sectors.classify_batch."""
    if not companies:
        return {}
    first = _call_business_profile_tool(client, companies)

    result: dict[str, dict] = {}
    retry_tickers = []
    for ticker, _name, _sector in companies:
        entry = first.get(ticker)
        if entry is None:
            continue
        if validate_no_advice_language(entry["business_desc"]).is_valid:
            result[ticker] = {
                "business_desc": entry["business_desc"],
                "suppliers": entry.get("suppliers", []),
                "customers": entry.get("customers", []),
            }
        else:
            retry_tickers.append(ticker)

    if retry_tickers:
        retry_companies = [c for c in companies if c[0] in retry_tickers]
        retry = _call_business_profile_tool(client, retry_companies)
        for ticker in retry_tickers:
            entry = retry.get(ticker)
            if entry is None:
                continue
            if validate_no_advice_language(entry["business_desc"]).is_valid:
                result[ticker] = {
                    "business_desc": entry["business_desc"],
                    "suppliers": entry.get("suppliers", []),
                    "customers": entry.get("customers", []),
                }

    return result
```

Create `backend/backfill_business_profiles.py`:

```python
"""One-time enrichment: generate a plain-language business description
plus supply-chain suppliers/customers for every existing Company missing
one (docs/NEWS_IMPACT_APP_SPEC.md §3.1). Reused forever after --
Company.business_desc/supply_chain_*_json are read at API-serialization
time, never written by the per-article analysis pipeline.

Safe to re-run: only targets companies where business_desc IS NULL,
commits per-batch so an interrupted run keeps whatever progress it made.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python backfill_business_profiles.py
"""
import json

from app.analysis.claude_client import build_client
from app.companies.business_profile import generate_business_profiles_batch
from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Company

BATCH_SIZE = 25  # companies per LLM call -- keeps prompt/response small and each batch independently retriable


def main() -> None:
    init_db()
    session = SessionLocal()
    client = build_client(settings.groq_api_keys, settings.anthropic_api_key or None)
    total = 0
    try:
        pending = session.query(Company).filter_by(business_desc=None).all()
        print(f"{len(pending)} companies to enrich")
        for i in range(0, len(pending), BATCH_SIZE):
            batch = pending[i : i + BATCH_SIZE]
            profiles = generate_business_profiles_batch(client, [(c.ticker, c.name, c.sector) for c in batch])
            for company in batch:
                profile = profiles.get(company.ticker)
                if profile:
                    company.business_desc = profile["business_desc"]
                    company.supply_chain_suppliers_json = json.dumps(profile["suppliers"])
                    company.supply_chain_customers_json = json.dumps(profile["customers"])
                    total += 1
            session.commit()
            print(f"  batch {i // BATCH_SIZE + 1} done ({len(batch)} companies)")
    finally:
        session.close()

    print(f"Business profile backfill complete: {total} companies enriched.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_business_profile.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/business_profile.py backend/backfill_business_profiles.py backend/tests/test_business_profile.py
git commit -m "feat: add company business-profile enrichment (business_desc, supply chain) + backfill script"
```

---

## Task 8: Peers (derived, same-sector lookup)

**Files:**
- Create: `backend/app/companies/peers.py`
- Test: `backend/tests/test_peers.py`

**Interfaces:**
- Produces: `get_sector_peers(session, company: Company, limit: int = 10) -> list[Company]`. Consumed by a later UI phase (Phase 7, stock deep-dive), not wired anywhere in this plan.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_peers.py`:

```python
from app.companies.peers import get_sector_peers
from app.models import Company


def test_get_sector_peers_returns_same_sector_companies(db_session):
    target = Company(ticker="A.NS", name="Company A", sector="banking", index_tier="NIFTY50")
    peer1 = Company(ticker="B.NS", name="Company B", sector="banking", index_tier="NIFTY50")
    peer2 = Company(ticker="C.NS", name="Company C", sector="banking", index_tier="OTHER")
    other_sector = Company(ticker="D.NS", name="Company D", sector="auto", index_tier="NIFTY50")
    db_session.add_all([target, peer1, peer2, other_sector])
    db_session.commit()

    peers = get_sector_peers(db_session, target)

    tickers = {p.ticker for p in peers}
    assert tickers == {"B.NS", "C.NS"}


def test_get_sector_peers_excludes_the_company_itself(db_session):
    target = Company(ticker="A.NS", name="Company A", sector="banking", index_tier="NIFTY50")
    db_session.add(target)
    db_session.commit()

    peers = get_sector_peers(db_session, target)

    assert target.ticker not in {p.ticker for p in peers}


def test_get_sector_peers_respects_limit(db_session):
    target = Company(ticker="A.NS", name="Company A", sector="banking", index_tier="NIFTY50")
    db_session.add(target)
    for i in range(15):
        db_session.add(Company(ticker=f"P{i}.NS", name=f"Peer {i}", sector="banking", index_tier="OTHER"))
    db_session.commit()

    peers = get_sector_peers(db_session, target, limit=5)

    assert len(peers) == 5


def test_get_sector_peers_empty_when_no_peers_exist(db_session):
    target = Company(ticker="A.NS", name="Company A", sector="banking", index_tier="NIFTY50")
    db_session.add(target)
    db_session.commit()

    assert get_sector_peers(db_session, target) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_peers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.peers'`.

- [ ] **Step 3: Implement**

Create `backend/app/companies/peers.py`:

```python
"""Same-sector peer lookup for the stock deep-dive's discovery doorway
(docs/NEWS_IMPACT_APP_SPEC.md §2 Level 4, §3.1 Stock.peers). Pure derived
data -- deliberately NOT stored as a Company column, unlike the spec's
literal data model (see this plan's Global Constraints for the
rationale). Peers are 100% derivable from Company.sector at read time;
storing them as a denormalized array would go stale the moment a
company's sector changes or a new peer is seeded, with no independent
value over recomputing it fresh -- same "derived, never persisted as
truth" discipline this architecture already applies to intensity/cap_tier
(see app/market/intensity.py, app/market/cap_tier.py).
"""
from sqlalchemy.orm import Session

from app.models import Company

DEFAULT_PEER_LIMIT = 10


def get_sector_peers(session: Session, company: Company, limit: int = DEFAULT_PEER_LIMIT) -> list[Company]:
    """Every other Company sharing ``company.sector``, ordered by ticker
    for a stable, deterministic result, capped at ``limit``. Excludes
    ``company`` itself. Queried fresh every call."""
    return (
        session.query(Company)
        .filter(Company.sector == company.sector, Company.id != company.id)
        .order_by(Company.ticker.asc())
        .limit(limit)
        .all()
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_peers.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/peers.py backend/tests/test_peers.py
git commit -m "feat: add get_sector_peers — derived same-sector peer lookup"
```

---

## Task 9: Wire `refine_alert` into the pipeline

**Files:**
- Modify: `backend/app/analysis/refinement.py` (append `refine_alert`)
- Modify: `backend/app/pipeline.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_refine_alert_wiring.py`

**Interfaces:**
- Consumes: `generate_event_summary`, `generate_impact_whys`, `generate_timeline_effects` (Tasks 4-6), `app.models.Company`, `app.models.TimelineEffect` (Task 3), `app.market.measure.MarketMove` (Phase 1).
- Produces: `refine_alert(client, session, alert, article, alert_companies: list, market_moves: list) -> None`. `_persist_alert` gains a `client=None` keyword parameter; when provided, calls `refine_alert` after building `AlertCompany`/`MarketMove` rows and before the `CascadeGap`/`ImpactEdge` loops.

- [ ] **Step 1: Add the `refine_alert` orchestrator**

Append to `backend/app/analysis/refinement.py`:

```python
from app.models import Company, TimelineEffect


def refine_alert(client, session, alert, article, alert_companies: list, market_moves: list) -> None:
    """Populate the LLM-explanation fields on an already-measured,
    already-persisted alert: Alert.summary_short/summary_long,
    AlertCompany.why (only for companies with a real measured excess
    move), and TimelineEffect rows. Called from app.pipeline._persist_alert
    once measurement (MarketMove) already exists for this alert's
    companies -- never before. Never raises: any generation function
    returning None/empty simply leaves the corresponding field(s) unset,
    same "omit rather than fabricate" discipline as the rest of this
    pipeline.
    """
    text = article.full_content or article.content

    summary = generate_event_summary(client, article.title, text)
    if summary:
        alert.summary_short = summary.get("summary_short")
        alert.summary_long = summary.get("summary_long")

    moves_by_company_id = {m.company_id: m for m in market_moves}
    measured = []
    for ac in alert_companies:
        move = moves_by_company_id.get(ac.company_id)
        if move is not None and move.measurement_status == "ok" and move.excess_move_pct is not None:
            company = session.get(Company, ac.company_id)
            if company is not None:
                measured.append({
                    "ticker": company.ticker, "name": company.name,
                    "direction": ac.direction, "excess_move_pct": move.excess_move_pct,
                    "_alert_company": ac,
                })

    if measured:
        whys = generate_impact_whys(client, article.title, text, [
            {k: v for k, v in m.items() if k != "_alert_company"} for m in measured
        ])
        for m in measured:
            why = whys.get(m["ticker"])
            if why:
                m["_alert_company"].why = why

    for effect in generate_timeline_effects(client, article.title, text):
        session.add(TimelineEffect(alert_id=alert.id, horizon=effect["horizon"], description=effect["description"]))
```

- [ ] **Step 2: Add the autouse conftest stub**

In `backend/tests/conftest.py`, append after `_no_real_market_move_fetch`:

```python
@pytest.fixture(autouse=True)
def _no_real_refinement_call(monkeypatch):
    # process_new_articles now threads `client` into _persist_alert, which
    # calls refine_alert (LLM summary/why/timeline generation) whenever a
    # client is provided -- real in production, but most existing pipeline
    # tests pass a bare `object()` sentinel as claude_client (no
    # chat.completions attribute at all), which would raise AttributeError
    # the instant refine_alert tried to use it. Stub it to a no-op by
    # default -- tests that DO care about refinement override this via
    # their own monkeypatch.setattr, which takes precedence.
    monkeypatch.setattr("app.pipeline.refine_alert", lambda *args, **kwargs: None)
```

- [ ] **Step 3: Write the failing wiring tests**

Create `backend/tests/test_refine_alert_wiring.py`:

```python
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.models import Alert, AlertCompany, Article, Company, MarketMove, TimelineEffect
from app.pipeline import process_new_articles
import app.pipeline as pipeline_module


def _company(ticker="RELIANCE.NS", sector="oil_gas"):
    return Company(ticker=ticker, name=f"Company {ticker}", sector=sector, index_tier="NIFTY50", market_cap=1.0)


def _article(db_session, title="Oil prices surge on supply disruption"):
    article = Article(source="test", url=f"https://example.com/{title}", title=title, content="crude oil markets react")
    db_session.add(article)
    db_session.commit()
    return article


def _fake_analysis(ticker="RELIANCE.NS"):
    return AnalysisOutput(
        category="oil_gas",
        companies=[CompanyMention(
            name=f"Company {ticker}", ticker=ticker, is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            key_points=["Crude eases"], confidence_score=85, time_horizon="Short-Term",
        )],
    )


def test_client_none_skips_refinement_entirely(db_session, monkeypatch):
    # Existing direct-call test sites (test_pipeline.py) call _persist_alert
    # with no client argument -- must behave exactly as before this plan.
    article = _article(db_session)
    alert = pipeline_module._persist_alert(db_session, article, category="oil_gas", entries=[], event_type="crude_oil")
    assert alert.summary_short is None
    assert alert.summary_long is None


def test_process_new_articles_populates_summary_and_why_when_measured(db_session, monkeypatch):
    company = _company()
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: _fake_analysis())

    def fake_measure(session, company_obj):
        from app.models import utcnow
        return MarketMove(
            company_id=company_obj.id, benchmark_ticker="^CNXENERGY",
            excess_move_pct=4.2, measurement_status="ok", measured_at=utcnow(),
        )
    monkeypatch.setattr(pipeline_module, "measure_company_move", fake_measure)

    def fake_refine_alert(client, session, alert, article_arg, alert_companies, market_moves):
        alert.summary_short = "Oil supply shock lifts refiners"
        alert.summary_long = "Crude prices jumped on a supply disruption. Refiners benefit from wider margins."
        for ac in alert_companies:
            ac.why = "Higher crude prices lift refining margins for this company."
        from app.models import TimelineEffect as TE
        session.add(TE(alert_id=alert.id, horizon="TODAY", description="Markets react immediately."))
    monkeypatch.setattr(pipeline_module, "refine_alert", fake_refine_alert)

    process_new_articles(db_session, claude_client=object())

    alert = db_session.query(Alert).one()
    assert alert.summary_short == "Oil supply shock lifts refiners"
    ac = db_session.query(AlertCompany).filter_by(alert_id=alert.id).one()
    assert ac.why == "Higher crude prices lift refining margins for this company."
    timeline = db_session.query(TimelineEffect).filter_by(alert_id=alert.id).all()
    assert len(timeline) == 1
    assert timeline[0].horizon == "TODAY"


def test_refine_alert_leaves_why_none_for_a_company_with_no_measured_move(db_session):
    from app.analysis.refinement import refine_alert
    from app.models import utcnow

    company = _company()
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="r", basis="direct_mention",
    )
    db_session.add(ac)
    no_data_move = MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        measurement_status="no_data", measured_at=utcnow(),
    )
    db_session.add(no_data_move)
    db_session.commit()

    class UnreachableClient:
        class _Completions:
            def create(self, **kwargs):
                raise AssertionError("must not call the LLM for an unmeasured company")

        @property
        def chat(self):
            from types import SimpleNamespace
            return SimpleNamespace(completions=self._Completions())

    refine_alert(UnreachableClient(), db_session, alert, article, [ac], [no_data_move])

    assert ac.why is None
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_refine_alert_wiring.py -v`
Expected: FAIL — `pipeline_module` has no `refine_alert`/`measure_company_move` attribute swap point for `refine_alert` yet, or the wiring loop doesn't collect `alert_companies`/`market_moves` yet, so nothing gets populated.

- [ ] **Step 5: Wire it into `_persist_alert`**

In `backend/app/pipeline.py`, add the import alongside the existing `app.market.measure` import:

```python
from app.analysis.refinement import refine_alert
```

Change the `_persist_alert` signature (currently `def _persist_alert(session, article, category, entries, event_type=None, gaps=None, edges=None):`) to add one new keyword parameter at the end:

```python
def _persist_alert(
    session: Session, article: Article, category: str, entries: list[dict], event_type: str | None = None,
    gaps: list[dict] | None = None, edges: list[dict] | None = None, client=None,
) -> Alert:
```

Change the existing `AlertCompany`-building loop to also collect the built rows:

```python
    alert_companies = []
    for entry in entries:
        alert_company = _build_alert_company(session, alert.id, article, category, entry)
        session.add(alert_company)
        alert_companies.append(alert_company)
```

Change the existing `MarketMove`-building loop (added in Phase 1) to also collect the built rows:

```python
    market_moves = []
    for entry in entries:
        company_obj = session.get(Company, entry["company_id"])
        if company_obj is not None:
            move = measure_company_move(session, company_obj)
            move.alert_id = alert.id
            session.add(move)
            market_moves.append(move)
```

Add the refinement call directly after that loop, before the `CascadeGap` loop:

```python
    if client is not None:
        refine_alert(client, session, alert, article, alert_companies, market_moves)
```

Update both call sites inside `process_new_articles` to pass the client through:

```python
            _persist_alert(session, article, reusable_alert.category, entries, event_type=reusable_alert.event_type, client=claude_client)
```

and

```python
        _persist_alert(
            session, article, analysis.category, resolved,
            event_type=analysis.event_type, gaps=analysis.gaps, edges=analysis.edges, client=claude_client,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_refine_alert_wiring.py -v`
Expected: all PASS.

- [ ] **Step 7: Run the full backend suite to confirm no regressions**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS — the new autouse `_no_real_refinement_call` fixture keeps every existing pipeline test's `refine_alert` a no-op, and `client=None`'s default keeps every direct `_persist_alert(...)` test-call site (in `test_pipeline.py`) behaving exactly as before.

- [ ] **Step 8: Commit**

```bash
git add backend/app/analysis/refinement.py backend/app/pipeline.py backend/tests/conftest.py backend/tests/test_refine_alert_wiring.py
git commit -m "feat: wire refine_alert into the pipeline after measurement"
```

---

## Task 10: Full-suite regression check

- [ ] **Step 1: Run the entire backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS — every task above is additive-only (new modules, new nullable columns, one new table, one new optional pipeline parameter guarded by an autouse test stub), so nothing pre-existing should regress.

- [ ] **Step 2: Commit (only if Step 1 required a fix)**

If Step 1 was clean, nothing to commit here. If it required a fix, commit it separately describing exactly what regressed and why.

---

## PHASE 3 STOP — required report

Report:
1. Full-suite pass/fail status (Task 10).
2. Confirmation that no LLM-generated number reaches any persisted field — every `summary_short`/`summary_long`/`why`/`TimelineEffect.description`/`business_desc` is validated via `validate_no_advice_language` before being written, with reject-and-regenerate-once-then-drop as the failure path.
3. Confirmation that a ripple company with no measured move (`MarketMove.measurement_status != "ok"`) never receives a fabricated `why`.
4. **Flag for confirmation:** `Stock.peers` was implemented as a derived, on-read function (`get_sector_peers`) rather than a stored `Company` column, per this plan's Global Constraints — deliberately consistent with the "derived, never persisted" discipline Phase 2 already applies to `intensity`/`cap_tier`, but a documented deviation from the spec's literal data model (§3.1 lists `peers: string[]` as a stored field). Confirm this reading is acceptable before Phase 4+ (UI) builds against it.
5. Any other spec ambiguity hit and how it was resolved (e.g. the `ripple_relationship.py` many-to-one mapping choices, `IMPACT_WHY_FRAMING`'s "sharp vs. modest" qualitative framing of the measured excess).

This plan ends here. Phase 4 (Level 0 feed + Level 1 summary UI) is a separate plan, written after this one ships and the report above is reviewed — per the task brief's HARD RULE, every phase with a UI component requires Playwright screenshots at 390px/1920px in both themes before being considered done.
