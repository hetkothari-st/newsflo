# Sector-Cascade Reasoning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-mega-prompt `analyze_article` with a 7-call sector-first reasoning chain (facts -> primary sectors -> primary companies -> cascade sectors L1 -> cascade companies L1 -> cascade sectors L2 -> cascade companies L2), and expand the sector taxonomy plus backfill existing companies into it so cascade reasoning can actually resolve to real companies.

**Architecture:** New `app/analysis/cascade.py` houses three reusable, parametrized stage functions (`_extract_facts`, `_identify_sectors`, `_identify_companies`) called 7 times total by a new `analyze_article` orchestrator, composing their output into the exact same `AnalysisOutput`/`CompanyMention` shape the rest of the codebase already consumes -- `app/pipeline.py`'s `_persist_alert`, `resolve_companies`, the frontend, none of them change. The old single-call `analyze_article`/`RECORD_ANALYSIS_TOOL`/`ANALYSIS_INSTRUCTIONS` in `app/analysis/claude_client.py` are deleted outright, not kept.

**Tech Stack:** Python/FastAPI backend, Pydantic models, Groq/Anthropic OpenAI-compatible tool-calling (existing `build_client`/`RotatingClient`/`FallbackClient`/`AnthropicAdapter` machinery, unchanged), pytest.

## Global Constraints

- Output stays wire-compatible: the composed result is the same `AnalysisOutput` (`category`, `event_type`, `companies: list[CompanyMention]`) shape that exists today. No changes to `app/pipeline.py`'s `_persist_alert`, `app/companies/resolution.py`, `AlertCompany`, or any frontend code.
- Model tiers (from the design spec): stage 1 (facts) and stages 2/4/6 (sector identification) use `FALLBACK_MODEL` only, no further fallback -- matches the `classify_relevance` precedent (`app/filtering/relevance.py`) of a single cheap call that either succeeds or fails, no MODEL->FALLBACK_MODEL dance. Stages 3/5/7 (company identification, the user-facing rationale/key_points text) use `MODEL` first, falling back to `FALLBACK_MODEL` on `RateLimitError` -- exactly the existing `analyze_article`'s `_call(MODEL)` / `except RateLimitError: _call(FALLBACK_MODEL)` pattern.
- Failure handling: stage 1 or 2 failing (no facts, or no primary sectors at all) propagates as an exception, failing the whole article -- identical to today's `ANALYSIS_FAILED` path in `app/pipeline.py`. A failure at stage 3 or later truncates the pipeline at that point: whatever stages completed successfully before the failure are still returned/persisted, later stages are simply skipped.
- Every company mention the pipeline produces sets `is_direct=True` (every stage always names specific companies, never falls back to generic sector-aggregate inference) -- this routes every mention through `resolve_companies`'s name/ticker matching path (`_find_direct_company`), never its `sector_inference` fallback branch. `impact_level` and `sector` are set **programmatically** by `_identify_companies` (from which stage/sector-group produced the mention), never asked of the LLM. `parent_ticker` **is** asked of the LLM for cascade stages (5/7) -- a real, specific economic-relationship judgment call that can't be derived mechanically -- constrained via a tool-schema enum to only the tickers of the actual parent-pool companies, so the model cannot hallucinate a nonexistent parent.
- The rulebook/playbook citation discipline (`RULEBOOK_TEXT`, `PLAYBOOKS_TEXT`, `evidence_refs` citing a `RULE_...` id, later matched against `get_rule()` in `app/pipeline.py:204` to populate `AlertCompany.rulebook_ids_json` for calibration) is load-bearing and MUST be preserved in the new company-identification stage prompt -- dropping it would silently break the confidence-calibration system.
- The plain-language WHY/HOW quality bar for `rationale`/`key_points` (no restated price/number, no vague sentiment, no unexplained jargon, causal chain spelled out in plain words) is this session's own hard-won prompt-quality fix -- it MUST be preserved verbatim in spirit in the new company-identification stage prompt, not diluted.
- New sectors added to `SECTORS` do NOT get their own `_other` fallback bucket (a correction to the design spec's own wording, caught during planning) -- that per-sector `_other` pattern belongs to `SUB_SECTOR_TAXONOMY` (one level below `SECTORS`), which this plan does not touch for the new sectors. All 18 `SECTORS` values (9 existing + 8 new + the single shared `other`) share ONE catch-all `"other"` value, exactly as today.

---

## File Structure

- Modify: `app/analysis/schemas.py` -- expand `SECTORS`, add `SECTOR_DEFINITIONS` (moved from `claude_client.py` and expanded with the 8 new sectors), add `FactsResult` and `SectorFinding` Pydantic models.
- Modify: `app/analysis/claude_client.py` -- delete `SECTOR_DEFINITIONS`, `ANALYSIS_INSTRUCTIONS`, `RECORD_ANALYSIS_TOOL`, `analyze_article`, and their now-unused imports. Keep `SYSTEM_PROMPT`, `MODEL`, `FALLBACK_MODEL`, `GROQ_BASE_URL`, `RotatingClient`, `AnthropicAdapter`, `FallbackClient`, `build_client` unchanged.
- Create: `app/companies/sector_classification.py` -- `classify_sector_batch`, `build_sector_classify_tool`, for the one-time backfill.
- Create: `backend/backfill_sectors.py` -- one-off script, untested (matches `backfill_subsectors.py`'s own convention of no test file).
- Create: `app/analysis/cascade.py` -- `_extract_facts`/`build_facts_tool` (stage 1), `_identify_sectors`/`build_sector_tool` (stages 2/4/6), `_identify_companies`/`build_company_tool`/`COMPANY_RATIONALE_INSTRUCTIONS` (stages 3/5/7), `analyze_article` (orchestrator).
- Modify: `app/pipeline.py` -- one-line import change.
- Create: `tests/test_sector_classification.py`.
- Create: `tests/test_cascade.py`.
- Modify: `tests/test_schemas.py` if it exists, else create it, for taxonomy/model tests.
- Modify: `tests/test_claude_client.py` -- delete tests exercising the removed `analyze_article`/`RECORD_ANALYSIS_TOOL`, keep all client-machinery tests (`RotatingClient`, `FallbackClient`, `AnthropicAdapter` translation, `build_client`) unchanged.

---

## Task 1: Sector taxonomy expansion

**Files:**
- Modify: `backend/app/analysis/schemas.py`
- Test: `backend/tests/test_schemas.py` (create if it doesn't exist)

**Interfaces:**
- Produces: `SECTORS: list[str]` (expanded, 18 values), `SECTOR_DEFINITIONS: str`, `FactsResult(BaseModel)`, `SectorFinding(BaseModel)` -- all consumed by Task 3/4/5's `cascade.py` stage functions and Task 2's `sector_classification.py`.

- [ ] **Step 1: Check whether `tests/test_schemas.py` already exists**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -c "import os; print(os.path.exists('tests/test_schemas.py'))"`

If `True`, read its current content before editing (append to it, don't overwrite). If `False`, you'll create it fresh in Step 2.

- [ ] **Step 2: Write the failing tests**

Create or append to `backend/tests/test_schemas.py`:

```python
from app.analysis.schemas import SECTOR_DEFINITIONS, SECTORS, CompanyMention, FactsResult, SectorFinding


def test_new_sectors_are_in_the_taxonomy():
    for sector in [
        "railways_transport", "construction_realestate", "defense", "agriculture",
        "consumer_durables", "media_entertainment", "chemicals", "textiles",
    ]:
        assert sector in SECTORS


def test_sectors_has_exactly_one_shared_other_bucket():
    assert SECTORS.count("other") == 1


def test_sector_definitions_covers_every_sector():
    for sector in SECTORS:
        assert f"- {sector}:" in SECTOR_DEFINITIONS


def test_facts_result_parses_required_fields():
    result = FactsResult(facts="Rupee fell 2% today.", category="macro_policy", event_type="currency_move")
    assert result.facts == "Rupee fell 2% today."
    assert result.category == "macro_policy"
    assert result.event_type == "currency_move"


def test_sector_finding_parent_sector_defaults_to_none():
    finding = SectorFinding(sector="banking", direction="bearish", mechanism="FX exposure hit.")
    assert finding.parent_sector is None


def test_sector_finding_accepts_parent_sector_for_cascade():
    finding = SectorFinding(sector="railways_transport", direction="bearish", mechanism="Import costs rise.", parent_sector="banking")
    assert finding.parent_sector == "banking"


def test_company_mention_defaults_impact_level_to_direct_when_absent():
    mention = CompanyMention(
        name="Reliance Industries", is_direct=True, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin", time_horizon="Short-Term",
    )
    assert mention.impact_level == "direct"
    assert mention.parent_ticker is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest tests/test_schemas.py -v`
Expected: FAIL -- `ImportError: cannot import name 'FactsResult'` (and/or the new-sector assertions failing if the file already existed with only old-sector coverage).

- [ ] **Step 4: Write the implementation**

In `backend/app/analysis/schemas.py`, replace the `SECTORS` line:

```python
SECTORS = ["oil_gas", "banking", "auto", "it", "pharma", "fmcg", "metals", "telecom", "infra", "other"]
```

with:

```python
SECTORS = [
    "oil_gas", "banking", "auto", "it", "pharma", "fmcg", "metals", "telecom", "infra",
    "railways_transport", "construction_realestate", "defense", "agriculture",
    "consumer_durables", "media_entertainment", "chemicals", "textiles", "other",
]

# Precise definitions the model must use for sector inference. Ambiguity here
# (e.g. treating "semiconductor" as close enough to "it") is what causes the
# resolver to attach real reasoning about one company (say, a Korean chip
# maker) to an unrelated company that merely shares a loosely-matched sector
# tag (e.g. an Indian IT services firm). Precision here is load-bearing.
# Moved here (was app.analysis.claude_client.SECTOR_DEFINITIONS) so both
# app.analysis.cascade and app.companies.sector_classification can import it
# without a circular dependency on claude_client.
SECTOR_DEFINITIONS = """
- oil_gas: oil & gas exploration, refining, and marketing companies only.
- banking: deposit-taking banks, NBFCs, and financial services firms only.
- auto: automobile and two-wheeler manufacturers, and auto component makers.
- it: INDIAN IT SERVICES / software consulting / outsourcing firms only \
(e.g. TCS, Infosys, Wipro). Does NOT include semiconductor, chip, or \
hardware manufacturers -- those have no matching sector in this system.
- pharma: pharmaceutical and healthcare companies, including hospitals and diagnostics.
- fmcg: fast-moving consumer goods, food & beverage, personal care.
- metals: metals, mining, and materials companies.
- telecom: telecommunications and network infrastructure operators.
- infra: industrial, infrastructure, construction/EPC, power/utilities, and heavy equipment.
- railways_transport: railways, aviation, shipping, ports, and logistics/road transport operators.
- construction_realestate: real estate developers (residential/commercial property) -- \
NOT EPC/construction contractors, those are infra.
- defense: defense and aerospace manufacturers.
- agriculture: agricultural inputs, fertilizers, agrochemicals, and seed companies.
- consumer_durables: consumer electronics and durable-goods manufacturers (appliances \
etc) -- distinct from fmcg's fast-moving, non-durable goods.
- media_entertainment: media, broadcasting, entertainment, and publishing companies.
- chemicals: specialty and commodity chemical manufacturers.
- textiles: textile and apparel manufacturers.
- other: none of the above.
""".strip()
```

Then, after the existing `IMPACT_LEVELS = [...]` line (before `class CompanyMention`), add:

```python
class FactsResult(BaseModel):
    facts: str
    category: str
    event_type: str


class SectorFinding(BaseModel):
    sector: str
    direction: str  # bullish | bearish
    mechanism: str
    # Set only for a cascade-hop finding (stages 4/6 of the sector-cascade
    # pipeline): the sector this one ripples from. None for a primary/
    # directly-affected sector (stage 2). See app.analysis.cascade.
    parent_sector: str | None = None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest tests/test_schemas.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Run the full backend test suite to check for regressions**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest -v`
Expected: No new failures beyond tests already known to reference the (still-present-until-Task-7) old `SECTOR_DEFINITIONS` import location -- at this point in the plan, `claude_client.py` still has its own `SECTOR_DEFINITIONS` copy (untouched until Task 7), so nothing should break yet. If anything unrelated fails, investigate before proceeding.

- [ ] **Step 7: Commit**

```bash
git add backend/app/analysis/schemas.py backend/tests/test_schemas.py
git commit -m "feat: expand sector taxonomy, add FactsResult/SectorFinding schemas"
```

---

## Task 2: Sector re-classification backfill

**Files:**
- Create: `backend/app/companies/sector_classification.py`
- Create: `backend/tests/test_sector_classification.py`
- Create: `backend/backfill_sectors.py`

**Interfaces:**
- Consumes: `SECTORS`, `SECTOR_DEFINITIONS` from `app.analysis.schemas` (Task 1). `MODEL`, `FALLBACK_MODEL` from `app.analysis.claude_client` (unchanged).
- Produces: `classify_sector_batch(client, tickers_and_names: list[tuple[str, str]]) -> dict[str, str]`, `build_sector_classify_tool() -> dict` -- used only by `backfill_sectors.py` in this task, not consumed by any later task.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_sector_classification.py`:

```python
import json
from types import SimpleNamespace

from app.companies.sector_classification import build_sector_classify_tool, classify_sector_batch
from app.analysis.schemas import SECTORS


class FakeToolCall:
    def __init__(self, name, arguments_dict):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments_dict))


class FakeCompletions:
    def __init__(self, response_input):
        self._response_input = response_input

    def create(self, **kwargs):
        message = SimpleNamespace(tool_calls=[FakeToolCall("record_sector_classifications", self._response_input)])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    def __init__(self, response_input):
        self.chat = SimpleNamespace(completions=FakeCompletions(response_input))


def test_build_sector_classify_tool_enum_matches_sectors():
    tool = build_sector_classify_tool()
    enum = tool["function"]["parameters"]["properties"]["classifications"]["items"]["properties"]["sector"]["enum"]
    assert enum == SECTORS


def test_classify_sector_batch_accepts_a_valid_response():
    client = FakeClient({"classifications": [{"ticker": "IRCTC.NS", "sector": "railways_transport"}]})
    result = classify_sector_batch(client, [("IRCTC.NS", "Indian Railway Catering and Tourism Corp")])
    assert result == {"IRCTC.NS": "railways_transport"}


def test_classify_sector_batch_falls_back_to_other_for_an_off_enum_value():
    client = FakeClient({"classifications": [{"ticker": "IRCTC.NS", "sector": "not_a_real_sector"}]})
    result = classify_sector_batch(client, [("IRCTC.NS", "Indian Railway Catering and Tourism Corp")])
    assert result == {"IRCTC.NS": "other"}


def test_classify_sector_batch_omits_a_ticker_the_model_did_not_address():
    client = FakeClient({"classifications": []})
    result = classify_sector_batch(client, [("IRCTC.NS", "Indian Railway Catering and Tourism Corp")])
    assert result == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest tests/test_sector_classification.py -v`
Expected: FAIL -- `ModuleNotFoundError: No module named 'app.companies.sector_classification'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/companies/sector_classification.py`:

```python
"""One-time top-level sector (re-)classification, using SECTORS as the
closed vocabulary (see app.analysis.schemas). Distinct from
app.companies.sub_sectors, which classifies one level below (a sub-sector
WITHIN an already-known sector) -- this module classifies the sector
itself. See backend/backfill_sectors.py for the one-time enrichment job
that uses this.
"""
import json

from openai import RateLimitError

from app.analysis.claude_client import FALLBACK_MODEL, MODEL
from app.analysis.schemas import SECTORS


def build_sector_classify_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_sector_classifications",
            "description": "Classify each company into a sector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "classifications": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ticker": {"type": "string"},
                                "sector": {"type": "string", "enum": SECTORS},
                            },
                            "required": ["ticker", "sector"],
                        },
                    },
                },
                "required": ["classifications"],
            },
        },
    }


def classify_sector_batch(client, tickers_and_names: list[tuple[str, str]]) -> dict[str, str]:
    """One tool-call classifying every (ticker, name) pair into a top-level
    SECTORS value, based on its actual, primary line of business. A ticker
    the model returns with an off-enum sector falls back to "other" rather
    than raising -- "other" is itself a valid SECTORS value, unlike
    app.companies.sub_sectors.classify_batch's per-sector "_other" bucket.
    A ticker the model omits entirely from its response is simply absent
    from the returned dict -- the caller (backfill_sectors.py) leaves it
    untouched and retries it on the next run, same "omit rather than
    mismatch" philosophy as app.companies.resolution.
    """
    tool = build_sector_classify_tool()
    listing = "\n".join(f"- {ticker}: {name}" for ticker, name in tickers_and_names)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a financial sector-classification analyst. Classify each "
                "listed company into exactly one sector from the given enum, based "
                "on its actual, primary line of business."
            ),
        },
        {"role": "user", "content": f"Companies to classify:\n{listing}"},
    ]

    def _call(model: str):
        return client.chat.completions.create(
            model=model,
            max_tokens=4096,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_sector_classifications"}},
            messages=messages,
        )

    try:
        response = _call(MODEL)
    except RateLimitError:
        response = _call(FALLBACK_MODEL)

    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == "record_sector_classifications"), None)
    if tool_call is None:
        return {}

    arguments = json.loads(tool_call.function.arguments)
    result: dict[str, str] = {}
    for entry in arguments.get("classifications", []):
        ticker = entry.get("ticker")
        sector = entry.get("sector")
        if not ticker:
            continue
        result[ticker] = sector if sector in SECTORS else "other"
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest tests/test_sector_classification.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Write the backfill script (no test -- matches `backfill_subsectors.py`'s existing convention of being an untested one-off)**

Create `backend/backfill_sectors.py`:

```python
"""One-time re-classification: re-tag every existing Company's top-level
sector using the expanded SECTORS taxonomy (see app/analysis/schemas.py).
Needed because the taxonomy grew 8 new sectors (railways_transport,
construction_realestate, defense, agriculture, consumer_durables,
media_entertainment, chemicals, textiles) that no existing company is
tagged into yet -- without this, sector-cascade reasoning
(app/analysis/cascade.py) can name real companies in these sectors but
app.companies.resolution will never find a matching Company row for them.

Safe to re-run: re-classifies every company (not just companies currently
in "other", since some may be mistagged into an existing sector too),
commits per-batch so an interrupted run keeps whatever progress it made. A
ticker the model omits from its response is left untouched and picked up
again next run (see app.companies.sector_classification.classify_sector_batch).

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python backfill_sectors.py
"""
from app.analysis.claude_client import build_client
from app.companies.sector_classification import classify_sector_batch
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
        companies = session.query(Company).all()
        num_batches = (len(companies) + BATCH_SIZE - 1) // BATCH_SIZE
        for i in range(0, len(companies), BATCH_SIZE):
            batch = companies[i : i + BATCH_SIZE]
            assignments = classify_sector_batch(client, [(c.ticker, c.name) for c in batch])
            for company in batch:
                sector = assignments.get(company.ticker)
                if sector and sector != company.sector:
                    company.sector = sector
                    total += 1
            session.commit()
            print(f"batch {i // BATCH_SIZE + 1}/{num_batches} done ({len(batch)} companies)")
    finally:
        session.close()

    print(f"Sector backfill complete: {total} companies re-tagged.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/companies/sector_classification.py backend/tests/test_sector_classification.py backend/backfill_sectors.py
git commit -m "feat: add sector re-classification backfill for the expanded taxonomy"
```

(Do NOT run `backfill_sectors.py` against production as part of this task -- that's an operational step for after the whole plan ships, since running it before `cascade.py` exists provides no benefit yet.)

---

## Task 3: Cascade stage 1 -- fact & mechanism extraction

**Files:**
- Create: `backend/app/analysis/cascade.py`
- Create: `backend/tests/test_cascade.py`

**Interfaces:**
- Consumes: `SYSTEM_PROMPT`, `FALLBACK_MODEL` from `app.analysis.claude_client`. `CATEGORIES`, `EVENT_TYPES`, `FactsResult` from `app.analysis.schemas`.
- Produces: `_extract_facts(client, title: str, content: str) -> FactsResult`, `build_facts_tool() -> dict` -- consumed by Task 6's orchestrator.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_cascade.py`:

```python
import json
from types import SimpleNamespace

import pytest

from app.analysis.cascade import _extract_facts


class FakeToolCall:
    def __init__(self, name, arguments_dict):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments_dict))


class ScriptedClient:
    """Returns a canned tool-call response keyed by the requested tool name
    (kwargs["tool_choice"]["function"]["name"]) -- order-independent, so a
    test can stub only the stage(s) it cares about. Raises AssertionError
    if a stage the test didn't script is actually called, surfacing an
    unexpected extra call immediately instead of a confusing downstream
    failure."""

    def __init__(self, responses: dict):
        self._responses = responses
        self.calls = []

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            name = kwargs["tool_choice"]["function"]["name"]
            self._outer.calls.append({"name": name, "model": kwargs.get("model")})
            if name not in self._outer._responses:
                raise AssertionError(f"unscripted stage called: {name}")
            response = self._outer._responses[name]
            if isinstance(response, Exception):
                raise response
            message = SimpleNamespace(tool_calls=[FakeToolCall(name, response)])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    @property
    def chat(self):
        return SimpleNamespace(completions=self._Completions(self))


def test_extract_facts_parses_response():
    client = ScriptedClient({
        "record_facts": {
            "facts": "Rupee fell 2% against the dollar today on weak trade data.",
            "category": "macro_policy",
            "event_type": "currency_move",
        },
    })

    result = _extract_facts(client, title="Rupee falls sharply", content="The rupee weakened 2% today.")

    assert result.facts == "Rupee fell 2% against the dollar today on weak trade data."
    assert result.category == "macro_policy"
    assert result.event_type == "currency_move"


def test_extract_facts_calls_fallback_model_only():
    from app.analysis.claude_client import FALLBACK_MODEL

    client = ScriptedClient({
        "record_facts": {"facts": "x", "category": "other", "event_type": "other"},
    })

    _extract_facts(client, title="t", content="c")

    assert client.calls == [{"name": "record_facts", "model": FALLBACK_MODEL}]


def test_extract_facts_raises_on_missing_tool_use_block():
    class NoToolCallClient:
        class _Completions:
            def create(self, **kwargs):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None))])

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions())

    with pytest.raises(ValueError, match="record_facts"):
        _extract_facts(NoToolCallClient(), title="Test Title", content="c")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest tests/test_cascade.py -v`
Expected: FAIL -- `ModuleNotFoundError: No module named 'app.analysis.cascade'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/analysis/cascade.py`:

```python
"""Sector-first, multi-step cascade reasoning: replaces the old single-call
app.analysis.claude_client.analyze_article with a 7-call chain (facts ->
primary sectors -> primary companies -> cascade sectors L1 -> cascade
companies L1 -> cascade sectors L2 -> cascade companies L2). See
docs/superpowers/specs/2026-07-20-sector-cascade-reasoning-design.md.

All three stage functions below (_extract_facts, _identify_sectors,
_identify_companies) are pure: given a client and inputs, they make exactly
one LLM call and return parsed, validated output, raising on a genuinely
malformed response (no tool_use block). The orchestrator (analyze_article,
added in a later task of this same plan) is responsible for sequencing
them and for the truncate-on-failure behavior described in the design spec.
"""
import json

from app.analysis.claude_client import FALLBACK_MODEL, SYSTEM_PROMPT
from app.analysis.schemas import CATEGORIES, EVENT_TYPES, FactsResult

FACTS_INSTRUCTIONS = (
    "Read this news article closely and extract its core facts and economic "
    "mechanism -- what actually happened, the key entities/numbers/geography "
    "involved, and WHY it matters economically. Do not name any companies or "
    "sectors yet -- that happens in a later step. Just establish the ground "
    "truth this analysis will reason from.\n\n"
    "Also classify this article's overall category (topical bucket, shown as "
    "a badge on the feed card) as exactly one of the values below -- "
    "lowercase-with-underscores, exact spelling, NEVER a sentence. If "
    "nothing matches, use \"other\":\n"
    f"{', '.join(CATEGORIES)}\n\n"
    "Also classify its event_type (the specific triggering event) as exactly "
    "one of the values below. If nothing matches, use \"other\":\n"
    f"{', '.join(EVENT_TYPES)}\n"
)


def build_facts_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_facts",
            "description": "Record the key facts/economic mechanism of this article and its classification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "facts": {
                        "type": "string",
                        "description": (
                            "What actually happened, the key entities/numbers/geography "
                            "involved, and the economic mechanism at play -- plain "
                            "prose, no company or sector names yet."
                        ),
                    },
                    "category": {"type": "string", "enum": CATEGORIES},
                    "event_type": {"type": "string", "enum": EVENT_TYPES},
                },
                "required": ["facts", "category", "event_type"],
            },
        },
    }


def _extract_facts(client, title: str, content: str) -> FactsResult:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                FACTS_INSTRUCTIONS
                + f"Title: {title}\n\nContent: "
                + f"{content or '(no content available -- reason only from the title)'}"
            ),
        },
    ]
    response = client.chat.completions.create(
        model=FALLBACK_MODEL,
        max_tokens=1024,
        tools=[build_facts_tool()],
        tool_choice={"type": "function", "function": {"name": "record_facts"}},
        messages=messages,
    )
    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == "record_facts"), None)
    if tool_call is None:
        raise ValueError(f"No record_facts tool_use block for article: {title!r}")
    arguments = json.loads(tool_call.function.arguments)
    return FactsResult.model_validate(arguments)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest tests/test_cascade.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/cascade.py backend/tests/test_cascade.py
git commit -m "feat: add cascade stage 1, fact and mechanism extraction"
```

---

## Task 4: Cascade stages 2/4/6 -- sector identification

**Files:**
- Modify: `backend/app/analysis/cascade.py`
- Modify: `backend/tests/test_cascade.py`

**Interfaces:**
- Consumes: `SYSTEM_PROMPT`, `FALLBACK_MODEL` from `app.analysis.claude_client`. `SECTORS`, `SECTOR_DEFINITIONS`, `SectorFinding` from `app.analysis.schemas` (Task 1).
- Produces: `_identify_sectors(client, facts: str, parent_sectors: list[SectorFinding] | None) -> list[SectorFinding]`, `build_sector_tool(cascade: bool, valid_parents: list[str] | None) -> dict` -- consumed by Task 6's orchestrator. `parent_sectors=None` means primary/directly-affected sectors (stage 2); a non-empty list means a cascade hop (stage 4 with primary sectors as `parent_sectors`, or stage 6 with hop-1 sectors as `parent_sectors`).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_cascade.py` (extend the existing import line to add `_identify_sectors`, and add `from app.analysis.schemas import SectorFinding` near the top):

```python
def test_identify_sectors_primary_parses_response():
    client = ScriptedClient({
        "record_sectors": {"sectors": [
            {"sector": "banking", "direction": "bearish", "mechanism": "FX exposure on the rupee's fall."},
        ]},
    })

    result = _identify_sectors(client, facts="The rupee fell 2% today.", parent_sectors=None)

    assert len(result) == 1
    assert result[0].sector == "banking"
    assert result[0].direction == "bearish"
    assert result[0].parent_sector is None


def test_identify_sectors_cascade_sets_parent_sector():
    primary = [SectorFinding(sector="banking", direction="bearish", mechanism="FX exposure.")]
    client = ScriptedClient({
        "record_sectors": {"sectors": [
            {
                "sector": "railways_transport", "direction": "bearish",
                "mechanism": "Higher import costs for fuel/rolling stock.", "parent_sector": "banking",
            },
        ]},
    })

    result = _identify_sectors(client, facts="The rupee fell 2% today.", parent_sectors=primary)

    assert result[0].sector == "railways_transport"
    assert result[0].parent_sector == "banking"


def test_identify_sectors_empty_result_is_valid():
    client = ScriptedClient({"record_sectors": {"sectors": []}})

    result = _identify_sectors(client, facts="Nothing much happened.", parent_sectors=None)

    assert result == []


def test_identify_sectors_calls_fallback_model_only():
    from app.analysis.claude_client import FALLBACK_MODEL

    client = ScriptedClient({"record_sectors": {"sectors": []}})

    _identify_sectors(client, facts="f", parent_sectors=None)

    assert client.calls == [{"name": "record_sectors", "model": FALLBACK_MODEL}]


def test_build_sector_tool_cascade_constrains_parent_sector_enum():
    tool = build_sector_tool(cascade=True, valid_parents=["banking", "auto"])
    parent_enum = tool["function"]["parameters"]["properties"]["sectors"]["items"]["properties"]["parent_sector"]["enum"]
    assert parent_enum == ["banking", "auto"]
    required = tool["function"]["parameters"]["properties"]["sectors"]["items"]["required"]
    assert "parent_sector" in required


def test_build_sector_tool_primary_has_no_parent_sector_field():
    tool = build_sector_tool(cascade=False, valid_parents=None)
    properties = tool["function"]["parameters"]["properties"]["sectors"]["items"]["properties"]
    assert "parent_sector" not in properties
```

Update the top of `backend/tests/test_cascade.py`'s import line from:
```python
from app.analysis.cascade import _extract_facts
```
to:
```python
from app.analysis.cascade import _extract_facts, _identify_sectors, build_sector_tool
from app.analysis.schemas import SectorFinding
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest tests/test_cascade.py -v`
Expected: FAIL -- `ImportError: cannot import name '_identify_sectors'`

- [ ] **Step 3: Write the implementation**

In `backend/app/analysis/cascade.py`, change the schemas import line from:
```python
from app.analysis.schemas import CATEGORIES, EVENT_TYPES, FactsResult
```
to:
```python
from app.analysis.schemas import CATEGORIES, EVENT_TYPES, SECTOR_DEFINITIONS, SECTORS, FactsResult, SectorFinding
```

Then append to the end of the file:

```python
def build_sector_tool(cascade: bool, valid_parents: list[str] | None) -> dict:
    """cascade=False builds the primary/directly-affected sector tool
    (stage 2, no parent_sector field). cascade=True builds the cascade
    tool (stages 4/6), adding a parent_sector field enum-constrained to
    valid_parents so the model cannot invent a nonexistent parent sector."""
    properties = {
        "sector": {"type": "string", "enum": SECTORS},
        "direction": {"type": "string", "enum": ["bullish", "bearish"]},
        "mechanism": {
            "type": "string",
            "description": "One-line explanation of why this sector is affected.",
        },
    }
    required = ["sector", "direction", "mechanism"]
    if cascade:
        properties["parent_sector"] = {"type": "string", "enum": valid_parents}
        required.append("parent_sector")
    return {
        "type": "function",
        "function": {
            "name": "record_sectors",
            "description": "Record sectors affected by this news, with direction and mechanism.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sectors": {
                        "type": "array",
                        "items": {"type": "object", "properties": properties, "required": required},
                    },
                },
                "required": ["sectors"],
            },
        },
    }


def _identify_sectors(client, facts: str, parent_sectors: list[SectorFinding] | None) -> list[SectorFinding]:
    """parent_sectors=None -> primary/directly-affected sector identification
    (stage 2). parent_sectors=<a prior stage's sectors> -> cascade: sectors
    affected AS A CONSEQUENCE of those already-identified sectors, one hop
    further out (stage 4 or 6)."""
    if parent_sectors is None:
        framing = (
            "Given these facts, identify every financial, business, or economic "
            "sector DIRECTLY affected by this news -- the sectors the news is "
            "actually about, not knock-on effects. For each, give its direction "
            "(bullish/bearish) and a one-line mechanism explaining WHY that "
            "sector is affected. Zero sectors is a correct answer when nothing "
            "in the facts genuinely supports one."
        )
        parent_context = ""
        valid_parents = None
    else:
        parent_lines = "\n".join(f"- {s.sector}: {s.mechanism}" for s in parent_sectors)
        framing = (
            "Given these facts and the sectors already identified as directly "
            "affected, identify sectors affected AS A CONSEQUENCE of those -- a "
            "ripple/knock-on effect, not the news's own direct subject. Only "
            "include a sector here if you have a genuine, specific mechanism "
            "for why it's affected because of the parent sector's own move, "
            "not because it's tangentially related. Zero cascade sectors is a "
            "correct answer when you don't have a real, specific one. For each, "
            "give its direction, a one-line mechanism, and which of the "
            "already-identified sectors it's rippling from (parent_sector)."
        )
        parent_context = f"\n\nAlready-identified sectors this may ripple from:\n{parent_lines}"
        valid_parents = [s.sector for s in parent_sectors]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{framing}\n\n"
                f"SECTOR DEFINITIONS:\n{SECTOR_DEFINITIONS}\n\n"
                f"Facts: {facts}"
                f"{parent_context}"
            ),
        },
    ]
    tool = build_sector_tool(cascade=parent_sectors is not None, valid_parents=valid_parents)
    response = client.chat.completions.create(
        model=FALLBACK_MODEL,
        max_tokens=2048,
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "record_sectors"}},
        messages=messages,
    )
    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == "record_sectors"), None)
    if tool_call is None:
        raise ValueError("No record_sectors tool_use block")
    arguments = json.loads(tool_call.function.arguments)
    return [SectorFinding.model_validate(s) for s in arguments.get("sectors", [])]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest tests/test_cascade.py -v`
Expected: All 9 tests PASS (3 from Task 3 + 6 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/cascade.py backend/tests/test_cascade.py
git commit -m "feat: add cascade stages 2/4/6, sector identification"
```

---

## Task 5: Cascade stages 3/5/7 -- company identification

**Files:**
- Modify: `backend/app/analysis/cascade.py`
- Modify: `backend/tests/test_cascade.py`

**Interfaces:**
- Consumes: `SYSTEM_PROMPT`, `MODEL`, `FALLBACK_MODEL` from `app.analysis.claude_client`. `RULEBOOK_TEXT` from `app.reasoning.rulebook`. `PLAYBOOKS_TEXT` from `app.reasoning.playbooks`. `TIME_HORIZONS`, `SectorFinding`, `CompanyMention` from `app.analysis.schemas`.
- Produces: `_identify_companies(client, facts: str, sectors: list[SectorFinding], impact_level: str, parent_pool: list[CompanyMention] | None) -> list[CompanyMention]`, `build_company_tool(parent_tickers: list[str] | None) -> dict` -- consumed by Task 6's orchestrator. `parent_pool=None` means the direct/primary stage (stage 3, `impact_level="direct"`); a non-empty list means a cascade stage (stage 5 with primary companies as `parent_pool` and `impact_level="indirect_l1"`, or stage 7 with hop-1 companies as `parent_pool` and `impact_level="indirect_l2"`).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_cascade.py`. Update the import line at the top from:
```python
from app.analysis.cascade import _extract_facts, _identify_sectors, build_sector_tool
from app.analysis.schemas import SectorFinding
```
to:
```python
from app.analysis.cascade import _extract_facts, _identify_companies, _identify_sectors, build_company_tool, build_sector_tool
from app.analysis.schemas import CompanyMention, SectorFinding
```

Then add:

```python
_BANKING_SECTOR = SectorFinding(sector="banking", direction="bearish", mechanism="FX exposure on the rupee's fall.")

_FULL_COMPANY_FIELDS = {
    "name": "HDFC Bank", "ticker": "HDFCBANK.NS", "direction": "bearish",
    "magnitude_low": 1.0, "magnitude_high": 2.0,
    "rationale": "Large forex book takes a mark-to-market hit as the rupee weakens.",
    "key_points": ["The rupee falling means HDFC Bank's dollar-denominated liabilities cost more in rupee terms."],
    "time_horizon": "Short-Term",
    "reasons": ["Forex mark-to-market loss on rupee depreciation."],
    "evidence_refs": ["article: rupee fell 2% today"],
    "risks": ["Rupee could recover quickly."],
    "assumptions": ["No RBI intervention in the next week."],
    "unknowns": ["Size of HDFC Bank's unhedged forex book."],
    "alternative_hypothesis": "A weaker rupee could also boost NRI deposit inflows, offsetting the forex loss.",
}


def test_identify_companies_direct_stage_sets_impact_level_and_sector():
    client = ScriptedClient({
        "record_sector_companies": {"sector_companies": [
            {"sector": "banking", "companies": [_FULL_COMPANY_FIELDS]},
        ]},
    })

    result = _identify_companies(client, facts="f", sectors=[_BANKING_SECTOR], impact_level="direct", parent_pool=None)

    assert len(result) == 1
    company = result[0]
    assert company.ticker == "HDFCBANK.NS"
    assert company.is_direct is True
    assert company.sector == "banking"
    assert company.impact_level == "direct"
    assert company.parent_ticker is None
    assert company.rationale == _FULL_COMPANY_FIELDS["rationale"]
    assert company.reasons == _FULL_COMPANY_FIELDS["reasons"]
    assert company.evidence_refs == _FULL_COMPANY_FIELDS["evidence_refs"]
    assert company.alternative_hypothesis == _FULL_COMPANY_FIELDS["alternative_hypothesis"]


def test_identify_companies_cascade_stage_requires_and_sets_parent_ticker():
    parent_pool = [CompanyMention(
        name="HDFC Bank", ticker="HDFCBANK.NS", is_direct=True, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        impact_level="direct",
    )]
    cascade_fields = dict(_FULL_COMPANY_FIELDS, name="IRCTC", ticker="IRCTC.NS", parent_ticker="HDFCBANK.NS")
    client = ScriptedClient({
        "record_sector_companies": {"sector_companies": [
            {"sector": "railways_transport", "companies": [cascade_fields]},
        ]},
    })

    result = _identify_companies(
        client, facts="f", sectors=[_BANKING_SECTOR], impact_level="indirect_l1", parent_pool=parent_pool,
    )

    assert result[0].impact_level == "indirect_l1"
    assert result[0].parent_ticker == "HDFCBANK.NS"


def test_identify_companies_direct_stage_calls_primary_model():
    from app.analysis.claude_client import MODEL

    client = ScriptedClient({"record_sector_companies": {"sector_companies": []}})

    _identify_companies(client, facts="f", sectors=[_BANKING_SECTOR], impact_level="direct", parent_pool=None)

    assert client.calls == [{"name": "record_sector_companies", "model": MODEL}]


def test_identify_companies_falls_back_to_secondary_model_on_rate_limit():
    from app.analysis.claude_client import FALLBACK_MODEL, MODEL

    class RateLimitOnceThenScripted(ScriptedClient):
        class _Completions(ScriptedClient._Completions):
            def create(self, **kwargs):
                if kwargs["model"] == MODEL:
                    from openai import RateLimitError
                    import httpx
                    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
                    response = httpx.Response(status_code=429, request=request)
                    self._outer.calls.append({"name": kwargs["tool_choice"]["function"]["name"], "model": kwargs["model"]})
                    raise RateLimitError("rate limited", response=response, body=None)
                return super().create(**kwargs)

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions(self))

    client = RateLimitOnceThenScripted({"record_sector_companies": {"sector_companies": []}})

    _identify_companies(client, facts="f", sectors=[_BANKING_SECTOR], impact_level="direct", parent_pool=None)

    assert client.calls == [
        {"name": "record_sector_companies", "model": MODEL},
        {"name": "record_sector_companies", "model": FALLBACK_MODEL},
    ]


def test_build_company_tool_cascade_constrains_parent_ticker_enum():
    tool = build_company_tool(parent_tickers=["HDFCBANK.NS"])
    props = tool["function"]["parameters"]["properties"]["sector_companies"]["items"]["properties"]["companies"]["items"]["properties"]
    assert props["parent_ticker"]["enum"] == ["HDFCBANK.NS"]


def test_build_company_tool_direct_has_no_parent_ticker_field():
    tool = build_company_tool(parent_tickers=None)
    props = tool["function"]["parameters"]["properties"]["sector_companies"]["items"]["properties"]["companies"]["items"]["properties"]
    assert "parent_ticker" not in props


def test_company_rationale_instructions_contains_rulebook_and_playbook_content():
    # ARPU appears only in the telecom playbook entry (verified absent from
    # RULEBOOK_TEXT and SECTOR_DEFINITIONS) -- a real, specific probe that
    # would catch a dropped PLAYBOOKS_TEXT interpolation.
    from app.analysis.cascade import COMPANY_RATIONALE_INSTRUCTIONS
    assert "RULE_CRUDE_OIL_UP" in COMPANY_RATIONALE_INSTRUCTIONS
    assert "ARPU" in COMPANY_RATIONALE_INSTRUCTIONS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest tests/test_cascade.py -v`
Expected: FAIL -- `ImportError: cannot import name '_identify_companies'`

- [ ] **Step 3: Write the implementation**

In `backend/app/analysis/cascade.py`:

Change the `claude_client` import line from:
```python
from app.analysis.claude_client import FALLBACK_MODEL, SYSTEM_PROMPT
```
to:
```python
from app.analysis.claude_client import FALLBACK_MODEL, MODEL, SYSTEM_PROMPT
```

Change the `schemas` import line from:
```python
from app.analysis.schemas import CATEGORIES, EVENT_TYPES, SECTOR_DEFINITIONS, SECTORS, FactsResult, SectorFinding
```
to:
```python
from app.analysis.schemas import (
    CATEGORIES, EVENT_TYPES, SECTOR_DEFINITIONS, SECTORS, TIME_HORIZONS,
    CompanyMention, FactsResult, SectorFinding,
)
```

Add two new top-level imports right after the existing `import json` line:
```python
from openai import RateLimitError

from app.reasoning.playbooks import PLAYBOOKS_TEXT
from app.reasoning.rulebook import RULEBOOK_TEXT
```

Then append to the end of the file:

```python
# Preserves this session's own hard-won plain-language WHY/HOW quality bar
# (see docs/superpowers/specs/2026-07-19-*-key-insights-quality*, and rules
# 6-8 of the now-deleted app.analysis.claude_client.ANALYSIS_INSTRUCTIONS)
# plus the rulebook/playbook citation discipline (rules 11-15 of the same,
# now-deleted, instructions) that app.pipeline._persist_alert's
# rulebook_ids_json extraction depends on -- both are load-bearing, not
# cosmetic prompt text.
COMPANY_RATIONALE_INSTRUCTIONS = (
    "For each company:\n"
    "- rationale: name the specific mechanism for THAT company -- its "
    "specific role (upstream producer vs refiner vs distributor vs miner: "
    "never assume every company in a sector plays the same role), its "
    "market position, and a real precedent if you know one. Never restate a "
    "price/number the article already reports as if it were analysis -- "
    "explain WHY this specific news moves this specific company, and HOW.\n"
    "- key_points: 1-4 plain-language sentences (full sentences, no word "
    "cap, typically 15-30 words) a reader with ZERO finance background can "
    "read once and immediately understand WHY this affects this company and "
    "HOW. Spell out the causal chain: [what happened] -> [what that changes "
    "for this company -- its costs, sales, profit, what its customers do] "
    "-> [why that's good or bad]. Replace or immediately unpack finance "
    "jargon (never leave \"margin compression\", \"deal pipeline "
    "pressure\", or similar unexplained). Never: (a) restating a "
    "price/number the article already reports; (b) a vague sentiment line "
    "with no mechanism; (c) a generic, always-true company fact untied to "
    "this specific news; (d) a jargon-dense sentence an ordinary reader "
    "would have to look up. Fewer, clearer sentences beat more, vaguer "
    "ones -- 1-2 entries is correct when that's all the genuine mechanism "
    "supports.\n"
    "- reasons: 1-4 short, distinct, individually-citable reasons "
    "supporting the direction call.\n"
    "- evidence_refs: one entry per `reasons` item -- either a rule id from "
    "ECONOMIC REASONING RULES below (e.g. \"RULE_REPO_RATE_CUT\"), a quoted "
    "or closely paraphrased fact from the article (prefix \"article: \"), "
    "or a specific historical precedent you actually know (prefix "
    "\"historical: \").\n"
    "- risks: 0-3 specific risks that could invalidate this call. "
    "assumptions: 0-3 things assumed true that, if wrong, change the call. "
    "unknowns: 0-3 pieces of missing information that would make this call "
    "more reliable.\n"
    "- alternative_hypothesis: one sentence describing a plausible "
    "competing interpretation, or why none is credible.\n"
    "- time_horizon: exactly one of Immediate, Short-Term, Medium-Term, "
    "Long-Term, based on when the mechanism actually plays out.\n\n"
    "Consult the ECONOMIC REASONING RULES and SECTOR PLAYBOOKS below. If a "
    "rule genuinely applies, use it to strengthen your rationale and "
    "include its rule id verbatim as one entry in that company's "
    "evidence_refs. Do not force-fit a rule that doesn't actually apply.\n"
    f"ECONOMIC REASONING RULES:\n{RULEBOOK_TEXT}\n\n"
    f"SECTOR PLAYBOOKS:\n{PLAYBOOKS_TEXT}"
)

_COMPANY_ITEM_PROPERTIES = {
    "name": {"type": "string"},
    "ticker": {"type": ["string", "null"]},
    "direction": {"type": "string", "enum": ["bullish", "bearish"]},
    "magnitude_low": {"type": "number"},
    "magnitude_high": {"type": "number"},
    "rationale": {"type": "string"},
    "key_points": {"type": "array", "items": {"type": "string"}},
    "time_horizon": {"type": "string", "enum": TIME_HORIZONS},
    "reasons": {"type": "array", "items": {"type": "string"}},
    "evidence_refs": {"type": "array", "items": {"type": "string"}},
    "risks": {"type": "array", "items": {"type": "string"}},
    "assumptions": {"type": "array", "items": {"type": "string"}},
    "unknowns": {"type": "array", "items": {"type": "string"}},
    "alternative_hypothesis": {"type": "string"},
}
_COMPANY_ITEM_REQUIRED = [
    "name", "direction", "magnitude_low", "magnitude_high", "rationale", "key_points",
    "time_horizon", "reasons", "evidence_refs", "risks", "assumptions", "unknowns",
    "alternative_hypothesis",
]


def build_company_tool(parent_tickers: list[str] | None) -> dict:
    """parent_tickers=None builds the direct/primary-stage tool (stage 3, no
    parent_ticker field). A non-empty list builds a cascade-stage tool
    (stages 5/7), adding a parent_ticker field enum-constrained to
    parent_tickers so the model cannot invent a nonexistent parent."""
    properties = dict(_COMPANY_ITEM_PROPERTIES)
    required = list(_COMPANY_ITEM_REQUIRED)
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


def _identify_companies(
    client, facts: str, sectors: list[SectorFinding], impact_level: str,
    parent_pool: list[CompanyMention] | None,
) -> list[CompanyMention]:
    """sectors: the sector(s) to find companies within (from a prior
    _identify_sectors call). impact_level: stamped onto every returned
    CompanyMention programmatically (never asked of the LLM). parent_pool:
    for a cascade stage, the companies (from the previous company-stage)
    each returned company must chain from via parent_ticker; None for the
    direct/primary stage (stage 3)."""
    sector_lines = "\n".join(f"- {s.sector} ({s.direction}): {s.mechanism}" for s in sectors)
    if parent_pool is None:
        framing = (
            "For each sector below, name the specific companies genuinely, "
            "directly affected -- both winners and losers where applicable (a "
            "single sector can have companies benefiting AND companies hurt by "
            "the same news, e.g. importers vs exporters on a currency move). "
            "Use your own knowledge of real companies and their actual "
            "business models; do not force-fit a company that doesn't "
            "genuinely fit. Zero companies for a sector is correct when none "
            "genuinely fit."
        )
        parent_context = ""
        parent_tickers = None
    else:
        # Filtered from the SAME iteration so names and tickers can never
        # misalign -- do not build parent_tickers and parent_lines from two
        # separately-filtered lists and zip() them; a parent_pool entry
        # with no ticker would then pair the wrong name with the wrong
        # ticker.
        parent_tickers = [c.ticker for c in parent_pool if c.ticker]
        parent_lines = "\n".join(f"- {c.ticker} ({c.name})" for c in parent_pool if c.ticker)
        framing = (
            "For each sector below, name the specific companies affected as a "
            "ripple from the already-identified companies listed. Every "
            "company you name MUST chain from one of those via parent_ticker "
            "(the exact ticker string) -- a real, specific economic link "
            "(supplier, customer, or close competitor), not merely being in "
            "the same sector. Zero companies for a sector is correct when you "
            "don't have a real, specific one."
        )
        parent_context = f"\n\nMust chain from one of these companies:\n{parent_lines}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{framing}\n\n"
                f"Facts: {facts}\n\n"
                f"Sectors:\n{sector_lines}"
                f"{parent_context}\n\n"
                f"{COMPANY_RATIONALE_INSTRUCTIONS}"
            ),
        },
    ]
    tool = build_company_tool(parent_tickers if parent_tickers else None)

    def _call(model: str):
        return client.chat.completions.create(
            model=model,
            max_tokens=8192,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_sector_companies"}},
            messages=messages,
        )

    try:
        response = _call(MODEL)
    except RateLimitError:
        response = _call(FALLBACK_MODEL)

    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == "record_sector_companies"), None)
    if tool_call is None:
        raise ValueError("No record_sector_companies tool_use block")
    arguments = json.loads(tool_call.function.arguments)

    mentions: list[CompanyMention] = []
    for group in arguments.get("sector_companies", []):
        sector = group.get("sector")
        for company in group.get("companies", []):
            mentions.append(CompanyMention(
                name=company["name"], ticker=company.get("ticker"), is_direct=True,
                sector=sector, direction=company["direction"],
                magnitude_low=company["magnitude_low"], magnitude_high=company["magnitude_high"],
                rationale=company["rationale"], key_points=company.get("key_points", []),
                time_horizon=company["time_horizon"], reasons=company.get("reasons", []),
                evidence_refs=company.get("evidence_refs", []), risks=company.get("risks", []),
                assumptions=company.get("assumptions", []), unknowns=company.get("unknowns", []),
                alternative_hypothesis=company.get("alternative_hypothesis"),
                impact_level=impact_level, parent_ticker=company.get("parent_ticker"),
            ))
    return mentions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest tests/test_cascade.py -v`
Expected: All 16 tests PASS (9 from Tasks 3-4 + 7 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/cascade.py backend/tests/test_cascade.py
git commit -m "feat: add cascade stages 3/5/7, company identification"
```

---

## Task 6: Orchestrator -- compose the 7 stages into `analyze_article`

**Files:**
- Modify: `backend/app/analysis/cascade.py`
- Modify: `backend/tests/test_cascade.py`

**Interfaces:**
- Consumes: `_extract_facts` (Task 3), `_identify_sectors` (Task 4), `_identify_companies` (Task 5) -- all in the same module.
- Produces: `analyze_article(client, title: str, content: str) -> AnalysisOutput` -- consumed by Task 7's `pipeline.py` wiring. Same signature and return type as the old `app.analysis.claude_client.analyze_article` it replaces.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_cascade.py`. Update the import line at the top from:
```python
from app.analysis.cascade import _extract_facts, _identify_companies, _identify_sectors, build_company_tool, build_sector_tool
from app.analysis.schemas import CompanyMention, SectorFinding
```
to:
```python
from app.analysis.cascade import analyze_article, _extract_facts, _identify_companies, _identify_sectors, build_company_tool, build_sector_tool
from app.analysis.schemas import CompanyMention, SectorFinding
```

Then add:

```python
def _full_company(name, ticker, parent_ticker=None):
    fields = dict(_FULL_COMPANY_FIELDS, name=name, ticker=ticker)
    if parent_ticker:
        fields["parent_ticker"] = parent_ticker
    return fields


def test_analyze_article_composes_all_seven_stages_end_to_end():
    # Sector/company stages are called multiple times with the same tool
    # name in one run (stage 2 vs 4 vs 6 all call record_sectors; stage 3
    # vs 5 vs 7 all call record_sector_companies) -- ScriptedClient as built
    # in Task 3 only supports ONE canned response per tool name. Use a
    # call-count-based variant here instead.
    class MultiStageClient:
        def __init__(self):
            self.calls = []
            self._sector_responses = [
                {"sectors": [{"sector": "banking", "direction": "bearish", "mechanism": "FX exposure."}]},
                {"sectors": [{
                    "sector": "railways_transport", "direction": "bearish",
                    "mechanism": "Import costs rise.", "parent_sector": "banking",
                }]},
                {"sectors": []},  # no hop-2 sectors found -- stops the chain
            ]
            self._company_responses = [
                {"sector_companies": [{"sector": "banking", "companies": [_full_company("HDFC Bank", "HDFCBANK.NS")]}]},
                {"sector_companies": [{
                    "sector": "railways_transport",
                    "companies": [_full_company("IRCTC", "IRCTC.NS", parent_ticker="HDFCBANK.NS")],
                }]},
            ]
            self._sector_call_count = 0
            self._company_call_count = 0

        class _Completions:
            def __init__(self, outer):
                self._outer = outer

            def create(self, **kwargs):
                name = kwargs["tool_choice"]["function"]["name"]
                self._outer.calls.append(name)
                if name == "record_facts":
                    response = {"facts": "The rupee fell 2% today.", "category": "macro_policy", "event_type": "currency_move"}
                elif name == "record_sectors":
                    response = self._outer._sector_responses[self._outer._sector_call_count]
                    self._outer._sector_call_count += 1
                elif name == "record_sector_companies":
                    response = self._outer._company_responses[self._outer._company_call_count]
                    self._outer._company_call_count += 1
                else:
                    raise AssertionError(f"unexpected tool: {name}")
                message = SimpleNamespace(tool_calls=[FakeToolCall(name, response)])
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions(self))

    client = MultiStageClient()

    result = analyze_article(client, title="Rupee falls sharply", content="The rupee weakened 2% today.")

    assert result.category == "macro_policy"
    assert result.event_type == "currency_move"
    assert len(result.companies) == 2
    direct, cascade = result.companies
    assert direct.ticker == "HDFCBANK.NS"
    assert direct.impact_level == "direct"
    assert direct.parent_ticker is None
    assert cascade.ticker == "IRCTC.NS"
    assert cascade.impact_level == "indirect_l1"
    assert cascade.parent_ticker == "HDFCBANK.NS"
    # 6 calls: facts, primary sectors, primary companies, L1 sectors, L1
    # companies, L2 sectors -- the L2-sector call DOES run (L1 sectors and
    # L1 companies-with-tickers are both non-empty, so the orchestrator's
    # guards let it through), but it returns zero L2 sectors, so stage 7
    # (L2 companies) never runs.
    assert client.calls == [
        "record_facts", "record_sectors", "record_sector_companies",
        "record_sectors", "record_sector_companies", "record_sectors",
    ]


def test_analyze_article_propagates_facts_stage_failure():
    client = ScriptedClient({"record_facts": ValueError("boom")})

    with pytest.raises(ValueError, match="boom"):
        analyze_article(client, title="t", content="c")


def test_analyze_article_propagates_primary_sector_stage_failure():
    client = ScriptedClient({
        "record_facts": {"facts": "f", "category": "other", "event_type": "other"},
        "record_sectors": ValueError("boom"),
    })

    with pytest.raises(ValueError, match="boom"):
        analyze_article(client, title="t", content="c")


def test_analyze_article_truncates_and_returns_direct_companies_when_primary_company_stage_fails():
    client = ScriptedClient({
        "record_facts": {"facts": "f", "category": "other", "event_type": "other"},
        "record_sectors": {"sectors": [{"sector": "banking", "direction": "bearish", "mechanism": "m"}]},
        "record_sector_companies": ValueError("boom"),
    })

    result = analyze_article(client, title="t", content="c")

    assert result.companies == []


def test_analyze_article_stops_cascade_when_primary_sectors_are_empty():
    client = ScriptedClient({
        "record_facts": {"facts": "f", "category": "other", "event_type": "other"},
        "record_sectors": {"sectors": []},
    })

    result = analyze_article(client, title="t", content="c")

    assert result.companies == []
    # No company stage should have run at all -- nothing to find companies
    # within when there are zero primary sectors.
    assert [c["name"] for c in client.calls] == ["record_facts", "record_sectors"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest tests/test_cascade.py -v`
Expected: FAIL -- `ImportError: cannot import name 'analyze_article'`

- [ ] **Step 3: Write the implementation**

Append to the end of `backend/app/analysis/cascade.py`:

```python
from app.analysis.schemas import AnalysisOutput  # noqa: E402 -- see note below


def analyze_article(client, title: str, content: str) -> AnalysisOutput:
    """Runs the 7-call sector-cascade chain and composes the result into the
    same AnalysisOutput shape app.pipeline.py already consumes. Failure
    handling (see docs/superpowers/specs/2026-07-20-sector-cascade-
    reasoning-design.md): a facts (stage 1) or primary-sector (stage 2)
    failure propagates, failing the whole article -- identical to the old
    single-call analyze_article's behavior. A failure at any later stage
    truncates the pipeline there: everything produced by stages that
    already succeeded is still returned.
    """
    facts_result = _extract_facts(client, title, content)
    primary_sectors = _identify_sectors(client, facts_result.facts, parent_sectors=None)

    all_companies: list = []
    if not primary_sectors:
        return AnalysisOutput(category=facts_result.category, event_type=facts_result.event_type, companies=all_companies)

    try:
        primary_companies = _identify_companies(
            client, facts_result.facts, primary_sectors, impact_level="direct", parent_pool=None,
        )
    except Exception:
        primary_companies = []
    all_companies.extend(primary_companies)

    l1_parent_tickers_present = [c for c in primary_companies if c.ticker]
    if l1_parent_tickers_present:
        try:
            l1_sectors = _identify_sectors(client, facts_result.facts, parent_sectors=primary_sectors)
            l1_companies = (
                _identify_companies(
                    client, facts_result.facts, l1_sectors, impact_level="indirect_l1",
                    parent_pool=l1_parent_tickers_present,
                )
                if l1_sectors else []
            )
        except Exception:
            l1_sectors, l1_companies = [], []
        all_companies.extend(l1_companies)

        l2_parent_tickers_present = [c for c in l1_companies if c.ticker]
        if l1_sectors and l2_parent_tickers_present:
            try:
                l2_sectors = _identify_sectors(client, facts_result.facts, parent_sectors=l1_sectors)
                l2_companies = (
                    _identify_companies(
                        client, facts_result.facts, l2_sectors, impact_level="indirect_l2",
                        parent_pool=l2_parent_tickers_present,
                    )
                    if l2_sectors else []
                )
            except Exception:
                l2_companies = []
            all_companies.extend(l2_companies)

    return AnalysisOutput(category=facts_result.category, event_type=facts_result.event_type, companies=all_companies)
```

Move that `from app.analysis.schemas import AnalysisOutput` line up to join the existing schemas import near the top of the file instead of leaving it inline (the inline placement above is only to show exactly what's new in this step) -- the final file should have ONE schemas import line:
```python
from app.analysis.schemas import (
    CATEGORIES, EVENT_TYPES, SECTOR_DEFINITIONS, SECTORS, TIME_HORIZONS,
    AnalysisOutput, CompanyMention, FactsResult, SectorFinding,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest tests/test_cascade.py -v`
Expected: All 20 tests PASS (16 from Tasks 3-5 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analysis/cascade.py backend/tests/test_cascade.py
git commit -m "feat: add cascade orchestrator, compose all 7 stages into analyze_article"
```

---

## Task 7: Wire into the pipeline, delete the old single-call analysis path

**Files:**
- Modify: `backend/app/pipeline.py`
- Modify: `backend/app/analysis/claude_client.py`
- Modify: `backend/tests/test_claude_client.py`

**Interfaces:**
- Consumes: `analyze_article` from `app.analysis.cascade` (Task 6).
- Produces: nothing new -- this task only rewires imports and removes now-dead code.

- [ ] **Step 1: Update the pipeline import**

In `backend/app/pipeline.py`, change:
```python
from app.analysis.claude_client import analyze_article
```
to:
```python
from app.analysis.cascade import analyze_article
```

- [ ] **Step 2: Run the pipeline test suite to confirm nothing breaks**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest tests/test_pipeline.py -v`
Expected: All tests PASS unchanged -- every `test_pipeline.py` test monkeypatches `pipeline_module.analyze_article` as a whole (verified: `monkeypatch.setattr(pipeline_module, "analyze_article", ...)`), so which module the real function lives in doesn't affect them.

- [ ] **Step 3: Delete the old single-call analysis code from `claude_client.py`**

In `backend/app/analysis/claude_client.py`:

Delete the import line:
```python
from app.analysis.schemas import CATEGORIES, EVENT_TYPES, IMPACT_LEVELS, SECTORS, TIME_HORIZONS, AnalysisOutput
```
(nothing remaining in this file uses any of these -- `SYSTEM_PROMPT`, `RotatingClient`, `AnthropicAdapter`, `FallbackClient`, `build_client` don't reference the schemas module.)

Delete the import lines:
```python
from app.reasoning.playbooks import PLAYBOOKS_TEXT
from app.reasoning.rulebook import RULEBOOK_TEXT
```
(moved to `app/analysis/cascade.py` in Task 5, no longer needed here.)

Delete the `SECTOR_DEFINITIONS` constant (moved to `app/analysis/schemas.py` in Task 1 -- keeping a second copy here would let the two drift apart).

Delete the `ANALYSIS_INSTRUCTIONS` constant in full (replaced by `cascade.py`'s per-stage instruction text).

Delete the `RECORD_ANALYSIS_TOOL` constant in full (replaced by `cascade.py`'s `build_facts_tool`/`build_sector_tool`/`build_company_tool`).

Delete the `analyze_article` function in full (replaced by `cascade.py`'s `analyze_article`).

Everything else in the file (`ANTHROPIC_MODEL`, `MODEL`, `FALLBACK_MODEL`, `GROQ_BASE_URL`, `SYSTEM_PROMPT`, `_RotatingCompletions`, `_RotatingChat`, `RotatingClient`, `_AnthropicCompletions`, `_AnthropicChat`, `AnthropicAdapter`, `_FallbackCompletions`, `_FallbackChat`, `FallbackClient`, `build_client`) stays unchanged.

- [ ] **Step 4: Update `tests/test_claude_client.py` -- remove tests for deleted code, keep client-machinery tests**

Delete these test functions entirely (they exercise the now-deleted `analyze_article`/`RECORD_ANALYSIS_TOOL`/`ANALYSIS_INSTRUCTIONS`, and their coverage has already been ported to `test_cascade.py` in Tasks 3, 5, and 6, or -- for `test_analyze_article_parses_sector_mention` and `test_analysis_instructions_covers_indirect_impact_rules` -- is intentionally retired, see the note after this list):

- `test_analyze_article_parses_direct_mention`
- `test_analyze_article_parses_sector_mention` -- **intentionally retired, not ported**: this tested the old `is_direct=False` sector-inference fallback path. The new pipeline's stage functions always set `is_direct=True` (see this plan's Global Constraints), so `resolve_companies`'s `sector_inference` branch is simply never exercised by pipeline-generated data anymore. The branch itself still exists in `app/companies/resolution.py` (out of scope to remove -- not part of this plan), just permanently unreached by the new pipeline.
- `test_analyze_article_raises_on_missing_tool_use_block` (ported as `test_extract_facts_raises_on_missing_tool_use_block` in Task 3)
- `test_analyze_article_falls_back_to_secondary_model_on_rate_limit` (ported as `test_identify_companies_falls_back_to_secondary_model_on_rate_limit` in Task 5)
- `test_analyze_article_works_end_to_end_via_anthropic_adapter` -- **intentionally retired, not ported**: `AnthropicAdapter`'s translation mechanics (system-message extraction, tool-schema conversion, response translation back to the OpenAI shape) are already fully and independently verified by `test_anthropic_adapter_translates_request_and_response_to_openai_shape` (kept, see below) using a generic tool -- that test doesn't depend on which specific tool schema is used, so it already proves the adapter works correctly for any of `cascade.py`'s tools too. `cascade.py`'s own orchestration logic is separately covered by `test_cascade.py`'s duck-typed `ScriptedClient` tests, which don't need to go through the real adapter translation layer to prove `analyze_article`'s sequencing/composition is correct.
- `test_record_analysis_tool_no_longer_requires_confidence_score` (the `confidence_score` field doesn't exist at all in `cascade.py`'s company tool schema -- there's nothing to test)
- `test_record_analysis_tool_requires_evidence_discipline_fields` (ported as part of `test_identify_companies_direct_stage_sets_impact_level_and_sector`'s field assertions in Task 5)
- `test_record_analysis_tool_requires_event_type_at_top_level` (ported as part of `test_extract_facts_parses_response`'s assertions in Task 3, since `event_type` is now a `record_facts` field)
- `test_analyze_article_parses_new_evidence_fields_when_present` (ported as part of `test_identify_companies_direct_stage_sets_impact_level_and_sector` in Task 5)
- `test_analysis_instructions_contains_rulebook_and_playbook_content` (ported as `test_company_rationale_instructions_contains_rulebook_and_playbook_content` in Task 5)
- `test_record_analysis_tool_requires_impact_level_and_parent_ticker` -- **intentionally retired, not ported**: `impact_level` is no longer an LLM-facing tool field at all (set programmatically); `parent_ticker`'s requiredness is covered by `test_build_company_tool_cascade_constrains_parent_ticker_enum` / `test_build_company_tool_direct_has_no_parent_ticker_field` in Task 5.
- `test_analysis_instructions_covers_indirect_impact_rules` -- **intentionally retired, not ported**: this was a prompt-text-content check (`"indirect_l1" in ANALYSIS_INSTRUCTIONS`); the underlying concept (cascade sector/company chaining) is now covered by actual behavioral tests (`test_identify_sectors_cascade_sets_parent_sector`, `test_identify_companies_cascade_stage_requires_and_sets_parent_ticker`, `test_analyze_article_composes_all_seven_stages_end_to_end`), which is a stronger form of coverage than a substring check on prompt text.
- `test_analyze_article_parses_indirect_impact_chain` (ported as part of `test_analyze_article_composes_all_seven_stages_end_to_end` in Task 6)
- `test_analyze_article_defaults_impact_level_to_direct_when_absent` (ported as `test_company_mention_defaults_impact_level_to_direct_when_absent` in Task 1 -- this was really testing `CompanyMention`'s own Pydantic default, not `analyze_article`'s behavior)

Also delete the now-unused `FakeClient`/`FakeChat`/`FakeCompletions`/`FakeToolCall` helper classes at the top of the file IF nothing else in the file still uses them after the deletions above (check: `test_anthropic_adapter_translates_request_and_response_to_openai_shape` uses `_FakeAnthropicMessages`/`_FakeAnthropicToolUseBlock`, a different set of helpers -- those stay).

Fix `test_anthropic_adapter_translates_request_and_response_to_openai_shape` (kept): it currently imports `RECORD_ANALYSIS_TOOL` from `app.analysis.claude_client`, which no longer exists. Replace:
```python
from app.analysis.claude_client import RECORD_ANALYSIS_TOOL, SYSTEM_PROMPT
```
with:
```python
from app.analysis.claude_client import SYSTEM_PROMPT
```
and replace the `tools=[RECORD_ANALYSIS_TOOL]` argument in that same test with an inline minimal fake tool (the test only checks that the adapter correctly translates a tool call's shape end-to-end, not any specific tool's content):
```python
FAKE_TOOL = {
    "type": "function",
    "function": {
        "name": "record_analysis",
        "description": "test tool",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}
```
and use `tools=[FAKE_TOOL]` in place of `tools=[RECORD_ANALYSIS_TOOL]`.

Keep every other test in the file unchanged: `test_build_client_returns_rotating_client_for_a_list`, `test_build_client_returns_plain_client_for_a_single_key`, `test_rotating_client_fails_over_to_next_key_on_rate_limit`, `test_rotating_client_sticks_with_working_key_on_subsequent_calls`, `test_rotating_client_raises_when_every_key_is_rate_limited`, `test_rotating_client_does_not_rotate_on_non_rate_limit_errors`, `test_build_client_wraps_in_fallback_when_anthropic_key_given`, `test_build_client_skips_fallback_wrapper_without_anthropic_key`, `test_fallback_client_uses_primary_when_it_succeeds`, `test_fallback_client_falls_through_to_secondary_on_anthropic_rate_limit`, `test_fallback_client_falls_through_to_secondary_on_openai_rate_limit`, `test_fallback_client_falls_through_to_secondary_on_anthropic_credit_failure`, `test_fallback_client_does_not_fall_through_on_other_errors`, `test_anthropic_adapter_translates_request_and_response_to_openai_shape` (fixed per above). Also remove the now-unused `FakeCompletionsModelFallback` class if `test_analyze_article_falls_back_to_secondary_model_on_rate_limit` (the only test that used it) was deleted above.

Also remove the now-unused `analyze_article` import from the file's top-level import block:
```python
from app.analysis.claude_client import (
    ANTHROPIC_MODEL,
    AnthropicAdapter,
    FallbackClient,
    RotatingClient,
    analyze_article,
    build_client,
)
```
becomes:
```python
from app.analysis.claude_client import (
    ANTHROPIC_MODEL,
    AnthropicAdapter,
    FallbackClient,
    RotatingClient,
    build_client,
)
```

- [ ] **Step 5: Run the full backend test suite**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -m pytest -v`
Expected: All tests PASS. Confirm no remaining references to the deleted symbols: `grep -rn "RECORD_ANALYSIS_TOOL\|ANALYSIS_INSTRUCTIONS\|claude_client import analyze_article\|claude_client.analyze_article" backend --include="*.py"` should return no matches (the only legitimate `analyze_article` references left should import it from `app.analysis.cascade`).

- [ ] **Step 6: Confirm the app still imports cleanly**

Run: `cd C:\Users\ST269\Desktop\newsflo\backend && python -c "from app import main; print('import OK')"`
Expected: `import OK`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/pipeline.py backend/app/analysis/claude_client.py backend/tests/test_claude_client.py
git commit -m "feat: wire the cascade orchestrator into the pipeline, remove the old single-call analysis path"
```

---

## Post-plan operational note (not a task -- do not automate)

After this plan ships and is deployed, `backend/backfill_sectors.py` should be run once against production (same pattern as the earlier `backfill_subsectors.py` run this session, via `railway run --service <backend> -- bash -c "DATABASE_URL=... PYTHONPATH=... PYTHONIOENCODING=utf-8 python backfill_sectors.py"`) so the expanded sector taxonomy actually has real companies tagged into it before cascade reasoning starts relying on them. This is an operational step to confirm with the user, not something to run automatically as part of task execution.
