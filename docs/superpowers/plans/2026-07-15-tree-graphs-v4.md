# Tree-Structured Graphs v4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Sector and Positive/Negative Split as real HTML/CSS hierarchical trees (matching the user's reference mockups), add Confidence Tree and Timeline Tree, remove the 5-company-per-alert cap, and add a Normal/Drilldown breadth toggle shared across every chart.

**Architecture:** Backend gains two new required fields on every company mention (`confidence_score`, `time_horizon`) threaded through the analysis pipeline, plus a prompt change removing the company-count cap. Frontend gains a shared, tested HTML/CSS tree primitive (`TreeRoot`/`TreeBranch`/`TreeLeaf`) that four chart components compose against, plus a page-level breadth toggle that filters `alert.companies` before handing it to whichever chart is active.

**Tech Stack:** Same as the existing charts feature — FastAPI/SQLAlchemy/pytest (backend), React 18 + TypeScript + Tailwind + Vitest (frontend). No new dependencies — trees are plain nested `<ul>`/`<li>` with CSS `border-left`/`border-bottom` connectors, no SVG, no canvas.

## Global Constraints

- No magnitude percentage is ever printed as a raw number anywhere on the charts page (existing constraint, still binding — `confidence_score` IS meant to be shown as a raw `NN%`, since it's a genuinely calibrated 0-100 signal the model is asked to differentiate, unlike `magnitude_low`/`magnitude_high` which the model can't reliably calibrate).
- Trees are plain nested HTML with CSS-drawn straight connector lines (`border-left`/`border-bottom`) — no SVG, no canvas, no curved paths. This is a deliberate reaction to the two prior SVG-tree failures; do not reintroduce SVG for tree rendering in this plan.
- Every existing color/direction token stays as-is: `text-bullish`/`text-bearish` for direction, the validated `SECTOR_COLOR` palette for sector branches — never invent a new ad hoc color for something an existing token already covers.
- `confidence_score` (0-100 int) is distinct from the existing `confidence` column (`"llm_estimate" | "calibrated"`, a data-quality flag) — never conflate the two or reuse one field name for both meanings.
- `time_horizon` uses exactly `Immediate | Short-Term | Medium-Term | Long-Term` (the master spec's vocabulary), not the mockup's 5 literal buckets.
- Impact Tree and all relationship-based graphs (Supply Chain, Ripple Effect, Knowledge Graph, Economic Chain, Multi-Level Impact Tree levels 2-5) are explicitly OUT OF SCOPE for this plan — do not build them, do not add scaffolding for them.
- Tapping any company leaf in any tree opens the existing `ReasoningPanel` (`frontend/src/components/ReasoningPanel.tsx`, signature `{ company: AlertCompany }`, unchanged) via the existing `useCompanySelection` hook — reuse both exactly as they are, do not modify them.

---

### Task 1: Backend — add `confidence_score` and `time_horizon` fields

**Files:**
- Modify: `backend/app/analysis/schemas.py`
- Modify: `backend/app/analysis/claude_client.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/db.py`
- Modify: `backend/app/companies/resolution.py`
- Modify: `backend/app/pipeline.py`
- Modify: `backend/app/routers/alerts.py`
- Test: `backend/tests/test_pipeline.py`, `backend/tests/test_api.py`, and any other test file constructing `CompanyMention(...)` directly (see Step 1 below — grep first, this is a required-field addition that breaks every existing call site).

**Interfaces:**
- Produces: `CompanyMention.confidence_score: int`, `CompanyMention.time_horizon: str`; `AlertCompany.confidence_score: int`, `AlertCompany.time_horizon: str`; both fields present in every `GET /api/alerts` and `GET /api/alerts/{id}` company entry.

- [ ] **Step 1: Find every existing `CompanyMention(` construction site**

Run: `cd backend && grep -rn "CompanyMention(" --include="*.py" .`

This will include at least `backend/tests/test_pipeline.py` (the fixture at line 33 quoted below) and possibly others (`test_analysis.py`, `test_resolution.py`, or similar — check whatever the grep actually returns). Making `confidence_score`/`time_horizon` required, non-defaulted fields means EVERY one of these call sites will fail to construct until updated — note the full list now, you'll update each one in Step 5.

- [ ] **Step 2: Add the two fields to the schema**

In `backend/app/analysis/schemas.py`, add a `TIME_HORIZONS` constant next to the existing `SECTORS` constant, and the two new fields to `CompanyMention`:

```python
from typing import Optional

from pydantic import BaseModel

SECTORS = ["oil_gas", "banking", "auto", "it", "pharma", "fmcg", "metals", "telecom", "infra", "other"]
TIME_HORIZONS = ["Immediate", "Short-Term", "Medium-Term", "Long-Term"]


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
    # 0-100: how directly evidenced THIS company's call is, not a general
    # "how confident is the model" score -- see the prompt rule for exactly
    # what should push this up or down.
    confidence_score: int
    # Exactly one of TIME_HORIZONS -- when the mechanism described in
    # `rationale` actually plays out, not how soon the news was published.
    time_horizon: str


class AnalysisOutput(BaseModel):
    category: str
    companies: list[CompanyMention]
```

- [ ] **Step 3: Add the new rules and tool schema fields**

In `backend/app/analysis/claude_client.py`, add two new numbered rules to `ANALYSIS_INSTRUCTIONS`, immediately after the existing rule 8 (the last rule, ending `"...instead of padding with a generic watch-this-space line...fabricated figure.\n\n"`). Change that rule's trailing `"\n\n"` to `"\n"` and append:

```python
    "9. Also set confidence_score: an integer 0-100 reflecting how directly "
    "evidenced THIS SPECIFIC company's call is -- a named company with a "
    "clear, specific stated mechanism should score high (80-100); a company "
    "reached only through sector-level inference, or where the link is "
    "plausible but not strongly evidenced, should score lower (40-70). "
    "Actually differentiate between your strongest and weakest picks in this "
    "same list -- do not default to a fixed number for every company.\n"
    "10. Also set time_horizon to exactly one of: Immediate (already priced "
    "in, or resolves within days), Short-Term (plays out over the next few "
    "weeks to a quarter), Medium-Term (multi-quarter), or Long-Term "
    "(structural, multi-year). Base it on when the mechanism you described "
    "in the rationale actually plays out, not on how recently the news was "
    "published.\n\n"
)
```

Import `TIME_HORIZONS` alongside the existing `SECTORS` import at the top of the file (find the existing `from app.analysis.schemas import ...` line and add `TIME_HORIZONS` to it).

Then in `RECORD_ANALYSIS_TOOL`'s company item `properties` dict, add two new entries after `key_points` (before the closing `},` of the properties dict, i.e. right before the `"required": [...]` line):

```python
                            "confidence_score": {"type": "integer", "minimum": 0, "maximum": 100},
                            "time_horizon": {"type": "string", "enum": TIME_HORIZONS},
```

And add both to the `"required"` list (currently `["name", "is_direct", "direction", "magnitude_low", "magnitude_high", "rationale", "key_points"]`):

```python
                        "required": [
                            "name", "is_direct", "direction", "magnitude_low", "magnitude_high",
                            "rationale", "key_points", "confidence_score", "time_horizon",
                        ],
```

- [ ] **Step 4: Add the columns to `AlertCompany` and register the schema-sync entries**

In `backend/app/models.py`, add two columns to `AlertCompany` (after the existing `key_points_json` line, before `basis`):

```python
    confidence_score = Column(Integer, nullable=False, default=50)
    time_horizon = Column(String, nullable=False, default="Short-Term")
```

In `backend/app/db.py`, append two tuples to `_ADDED_COLUMNS` (this project has no Alembic — every new column on an existing table must be registered here, per the comment already on that list):

```python
_ADDED_COLUMNS = [
    ("articles", "image_url", "VARCHAR"),
    ("alert_companies", "key_points_json", "TEXT"),
    ("companies", "isin", "VARCHAR"),
    ("users", "email_alerts_enabled", "INTEGER DEFAULT 1"),
    ("alert_companies", "confidence_score", "INTEGER DEFAULT 50"),
    ("alert_companies", "time_horizon", "VARCHAR DEFAULT 'Short-Term'"),
]
```

- [ ] **Step 5: Update every `CompanyMention(...)` call site found in Step 1**

For each site, add `confidence_score=<int>, time_horizon=<one of TIME_HORIZONS>` matching whatever the surrounding test is asserting. For the known site in `backend/tests/test_pipeline.py` (around line 33-37):

```python
    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            key_points=["Crude eases", "Refining margins widen"],
            confidence_score=85, time_horizon="Short-Term",
        )],
    )
```

Apply the same pattern (add `confidence_score=<int>, time_horizon=<value>` as the last two constructor args) to every other site the Step 1 grep found. Use a plausible value for each — the exact number doesn't matter for these tests, only that construction succeeds.

- [ ] **Step 6: Pass the fields through `resolve_companies`**

In `backend/app/companies/resolution.py`, `_to_resolved` (lines 21-30) is the single conversion point both branches of `resolve_companies` call — add the two new fields there so both the direct-mention and sector-inference paths (including the sector-inference fan-out, which calls `_to_resolved` once per company sharing the same source `mention`) get them automatically, identically to how `direction`/`rationale`/`key_points` already work:

```python
def _to_resolved(company: Company, mention: CompanyMention, basis: str) -> dict:
    return {
        "company_id": company.id,
        "direction": mention.direction,
        "magnitude_low": mention.magnitude_low,
        "magnitude_high": mention.magnitude_high,
        "rationale": mention.rationale,
        "key_points": mention.key_points,
        "confidence_score": mention.confidence_score,
        "time_horizon": mention.time_horizon,
        "basis": basis,
    }
```

- [ ] **Step 7: Persist the fields**

In `backend/app/pipeline.py`, `_persist_alert`'s `AlertCompany(...)` construction (around line 128-138), add the two fields:

```python
        session.add(AlertCompany(
            alert_id=alert.id,
            company_id=entry["company_id"],
            direction=entry["direction"],
            magnitude_low=magnitude_low,
            magnitude_high=magnitude_high,
            rationale=entry["rationale"],
            key_points_json=json.dumps(entry.get("key_points") or []),
            confidence_score=entry["confidence_score"],
            time_horizon=entry["time_horizon"],
            basis=entry["basis"],
            confidence=confidence,
        ))
```

- [ ] **Step 8: Serialize the fields in the API response**

In `backend/app/routers/alerts.py`, `_serialize_alert`'s per-company dict construction (around line 36-45), add the two fields:

```python
        companies.append({
            "company_id": ac.company_id, "ticker": ac.company.ticker, "name": ac.company.name,
            "index_tier": ac.company.index_tier, "sector": ac.company.sector, "direction": ac.direction,
            "magnitude_low": ac.magnitude_low, "magnitude_high": ac.magnitude_high,
            "rationale": rationale, "key_points": key_points,
            "confidence_score": ac.confidence_score, "time_horizon": ac.time_horizon,
            "basis": ac.basis, "confidence": ac.confidence,
            "market": infer_market(ac.company.ticker),
            "in_my_holdings": ac.company_id in held_company_ids,
            "past_mentions": mentions_before(mentions_index, ac.company_id, alert.created_at),
        })
```

- [ ] **Step 9: Write the failing tests**

Add to `backend/tests/test_pipeline.py`, extending the existing end-to-end test (`test_process_new_articles_creates_alert_end_to_end`) with new assertions after the existing `assert alert_companies[0].magnitude_high == 4.0` line:

```python
    assert alert_companies[0].confidence_score == 85
    assert alert_companies[0].time_horizon == "Short-Term"
```

Add to `backend/tests/test_api.py`, extending `test_list_alerts_returns_nested_companies` — add `confidence_score=85, time_horizon="Short-Term"` to the existing `AlertCompany(...)` construction (around line 31-36), and two new assertions after the existing `assert body[0]["companies"][0]["key_points"] == [...]` line:

```python
    assert body[0]["companies"][0]["confidence_score"] == 85
    assert body[0]["companies"][0]["time_horizon"] == "Short-Term"
```

Add a new test to `backend/tests/test_pipeline.py` confirming the sector-inference fan-out copies both new fields identically to every resulting row (mirroring the existing pattern around line 202-207 that already checks `direction`/`rationale`/`basis` fan out identically):

```python
def test_sector_inference_fan_out_copies_confidence_and_horizon_to_every_row(db_session, monkeypatch):
    for ticker, tier in [("A.NS", "NIFTY50"), ("B.NS", "NIFTYNEXT50")]:
        db_session.add(Company(ticker=ticker, name=ticker, sector="oil_gas", index_tier=tier, market_cap=1.0))
    db_session.commit()

    article = Article(source="test", url="https://example.com/b", title="Oil sector news", content="x")
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="oil sector", ticker=None, is_direct=False, sector="oil_gas",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="sector-wide tailwind",
            key_points=[], confidence_score=55, time_horizon="Medium-Term",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    process_new_articles(db_session, claude_client=object())

    alert = db_session.query(Alert).one()
    rows = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    assert len(rows) == 2
    assert all(r.confidence_score == 55 for r in rows)
    assert all(r.time_horizon == "Medium-Term" for r in rows)
```

- [ ] **Step 10: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_pipeline.py tests/test_api.py -v`
Expected: FAIL — `confidence_score`/`time_horizon` don't exist on the model/schema yet at the point these tests are first written (if you're following TDD strictly, write the tests before Steps 2-8; if you've already done Steps 2-8, this step instead confirms the code you just wrote makes them pass — run it either way and record the actual result).

- [ ] **Step 11: Run the full backend suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass, including every site fixed in Step 5 and Step 9's new tests.

- [ ] **Step 12: Commit**

```bash
git add backend/app/analysis/schemas.py backend/app/analysis/claude_client.py backend/app/models.py backend/app/db.py backend/app/companies/resolution.py backend/app/pipeline.py backend/app/routers/alerts.py backend/tests/
git commit -m "feat: add confidence_score and time_horizon to the analysis pipeline"
```

---

### Task 2: Backend — remove the 5-company cap

**Files:**
- Modify: `backend/app/analysis/claude_client.py`

**Interfaces:**
- Consumes: `ANALYSIS_INSTRUCTIONS` (Task 1's version, with rules 1-10 already present).
- Produces: an updated rule 5 and rule 1 with no numeric cap.

- [ ] **Step 1: Edit rule 5**

Rule 5 currently reads (verbatim): *"5. List at most 5 companies total, fewer if you are not genuinely confident in more. If nothing in the article has a specific, defensible link to a real company or one of the sectors above, return an empty companies list -- that is a correct answer, not a failure.\n"*

Replace with:

```python
    "5. List every company with a genuine, specific, defensible link to this "
    "article -- there is no fixed cap on how many. Do not pad the list to "
    "reach a target count, and do not omit a real one to stay under an old "
    "limit. If nothing in the article has a specific, defensible link to a "
    "real company or one of the sectors above, return an empty companies "
    "list -- that is a correct answer, not a failure.\n"
```

- [ ] **Step 2: Edit rule 1's secondary cap reference**

Rule 1 currently contains (verbatim, mid-rule): *"...This applies EVEN for a sector-wide catalyst -- if you can name the 3-5 specific companies you know are most exposed, name them individually with is_direct=true rather than reaching for sector=<value>..."*

Replace `"the 3-5 specific companies you know are most exposed"` with `"the specific companies you know are most exposed"` (drop the numeric range, keep everything else in that sentence identical).

- [ ] **Step 3: Confirm the tool schema has no structural cap**

Read `RECORD_ANALYSIS_TOOL`'s `companies` array definition (`"type": "array", "items": {...}`) — confirm there is no `"maxItems"` key on it (there wasn't one before this plan; this step is just a verification, not an edit, since Task 1 didn't add one either). If one exists for any reason, remove it.

- [ ] **Step 4: Manual real-article verification**

This is a real behavior change to a production LLM pipeline — it needs verification against real content, not just unit-test fixtures (which use short, synthetic article text and won't reveal padding/quality-degradation behavior).

Using the local venv, pick 5-10 recent real articles already in the local dev database (or the `newsflo.db` copy used earlier this session) and re-run `analyze_article` against their actual stored `content`, comparing the company count and rationale quality against what the OLD prompt (Task 1's version, pre-Task-2 edit) would have produced for the same articles. A quick way to do this: write a throwaway script in the scratchpad directory that loads N articles, calls `analyze_article` once with the current (uncapped) prompt, and prints `category` + each company's `name`/`is_direct`/`confidence_score`/`rationale` for manual read-through. Confirm:
- Company counts for genuinely multi-company articles increase meaningfully (not just always capping at exactly 5 anymore) when the article supports it.
- Rationale quality doesn't degrade — no generic, copy-pasteable-across-companies rationales creeping in as count rises (rule 6 still applies unchanged).
- No runaway company counts on broad macro articles (rule 4's "don't chain unrelated sector inferences" still bounds this).

Record the before/after counts and a brief quality read in the task's commit message or report — this is the evidence that the cap removal didn't silently degrade output quality.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass (no test asserts on the old 5-company cap as a hard limit; if one does, that test was over-specified and should be corrected to not assume a cap, since the cap itself is what's being removed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/analysis/claude_client.py
git commit -m "feat: remove the 5-company-per-alert cap"
```

---

### Task 3: Frontend — `confidence_score`/`time_horizon` types + `rankByConfidence`/`groupByTimeHorizon`

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/features/visualize/transforms.ts`
- Modify: `frontend/src/features/visualize/transforms.test.ts`

**Interfaces:**
- Produces: `AlertCompany.confidence_score: number`, `AlertCompany.time_horizon: string`; `rankByConfidence(companies: AlertCompany[]): AlertCompany[]`; `groupByTimeHorizon(companies: AlertCompany[]): CompanyGroup[]`; `TIME_HORIZON_ORDER: readonly string[]`.

- [ ] **Step 1: Add the two new fields to the `AlertCompany` interface**

In `frontend/src/lib/api.ts`, add to the `AlertCompany` interface (after the existing `key_points: string[];` line, before `basis`):

```typescript
  confidence_score: number; // 0-100, how directly evidenced this company's call is
  time_horizon: string; // Immediate | Short-Term | Medium-Term | Long-Term
```

- [ ] **Step 2: Write the failing tests**

Add to `frontend/src/features/visualize/transforms.test.ts` (find the existing `company(overrides)` fixture helper used by the `rankByMagnitude` describe block and reuse it, adding `confidence_score: 50, time_horizon: 'Short-Term'` to its defaults so every existing test in the file keeps compiling — TypeScript will error on the fixture helper itself if these fields are missing from its returned object, since `AlertCompany` now requires them):

```typescript
describe('rankByConfidence', () => {
  it('sorts descending by confidence_score', () => {
    const weak = company({ company_id: 1, confidence_score: 40 });
    const strong = company({ company_id: 2, confidence_score: 95 });
    const mid = company({ company_id: 3, confidence_score: 70 });

    expect(rankByConfidence([weak, strong, mid]).map((c) => c.company_id)).toEqual([2, 3, 1]);
  });

  it('keeps input order for equal scores (stable sort)', () => {
    const a = company({ company_id: 1, confidence_score: 80 });
    const b = company({ company_id: 2, confidence_score: 80 });

    expect(rankByConfidence([a, b]).map((c) => c.company_id)).toEqual([1, 2]);
  });

  it('returns an empty array for an empty input', () => {
    expect(rankByConfidence([])).toEqual([]);
  });
});

describe('groupByTimeHorizon', () => {
  it('groups companies into fixed-order horizon buckets, dropping empty ones', () => {
    const groups = groupByTimeHorizon([
      company({ company_id: 1, time_horizon: 'Long-Term' }),
      company({ company_id: 2, time_horizon: 'Immediate' }),
      company({ company_id: 3, time_horizon: 'Immediate' }),
    ]);
    expect(groups.map((g) => g.key)).toEqual(['Immediate', 'Long-Term']);
    expect(groups[0].companies).toHaveLength(2);
    expect(groups[1].companies).toHaveLength(1);
  });

  it('returns an empty array for an empty input', () => {
    expect(groupByTimeHorizon([])).toEqual([]);
  });
});
```

Update the import line at the top of `transforms.test.ts` to include `rankByConfidence, groupByTimeHorizon` alongside whatever's already imported from `./transforms`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/features/visualize/transforms.test.ts`
Expected: FAIL — `rankByConfidence`/`groupByTimeHorizon` not exported yet, and/or the fixture helper's return type error if you haven't updated it yet.

- [ ] **Step 4: Implement**

Add to `frontend/src/features/visualize/transforms.ts`, after the existing `rankByMagnitude` function:

```typescript
export function rankByConfidence(companies: AlertCompany[]): AlertCompany[] {
  return [...companies].sort((a, b) => b.confidence_score - a.confidence_score);
}

export const TIME_HORIZON_ORDER = ['Immediate', 'Short-Term', 'Medium-Term', 'Long-Term'] as const;

export function groupByTimeHorizon(companies: AlertCompany[]): CompanyGroup[] {
  return TIME_HORIZON_ORDER.map((horizon) => ({
    key: horizon,
    label: horizon,
    companies: companies.filter((c) => c.time_horizon === horizon),
  })).filter((g) => g.companies.length > 0);
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/features/visualize/transforms.test.ts`
Expected: PASS.

- [ ] **Step 6: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all tests pass — check whether any OTHER test file's inline `company(overrides)` fixture (several chart test files define their own copy, per the established pattern in this codebase) now fails to type-check because `AlertCompany` requires the two new fields; if so, add `confidence_score: 50, time_horizon: 'Short-Term'` to that fixture's defaults too.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/features/visualize/transforms.ts frontend/src/features/visualize/transforms.test.ts
git commit -m "feat: add confidence_score/time_horizon types and rankByConfidence/groupByTimeHorizon"
```

Note: this task's commit will likely also need to touch every existing chart test file's local `company()` fixture (`SectorTreemap.test.tsx`, `TierRows.test.tsx`, `ImpactBar.test.tsx`, `SplitDonut.test.tsx` — though the latter two are deleted/replaced in later tasks, so only `TierRows.test.tsx` and `ImpactBar.test.tsx` need a lasting fix here). Add `confidence_score: 50, time_horizon: 'Short-Term',` to each of their fixture defaults now, in this task, so the whole suite compiles cleanly before later tasks build on top of it.

---

### Task 4: Frontend — sequential confidence color ramp

**Files:**
- Modify: `frontend/src/features/visualize/colors.ts`
- Modify: `frontend/src/features/visualize/colors.test.ts`

**Interfaces:**
- Produces: `confidenceColor(score: number): string`.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/features/visualize/colors.test.ts`:

```typescript
describe('confidenceColor', () => {
  it('returns a hex color string for any score 0-100', () => {
    for (const score of [0, 20, 40, 55, 80, 100]) {
      expect(confidenceColor(score)).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it('is monotonic: higher scores map to later (darker) ramp steps, never an earlier one', () => {
    const RAMP_ORDER = ['#C7D2E8', '#9FB3D9', '#6C8CD5', '#3D5FA8', '#1F3D7A'];
    let lastIndex = -1;
    for (const score of [0, 25, 50, 75, 100]) {
      const idx = RAMP_ORDER.indexOf(confidenceColor(score));
      expect(idx).toBeGreaterThanOrEqual(lastIndex);
      lastIndex = idx;
    }
  });
});
```

Update the import line to include `confidenceColor`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/colors.test.ts`
Expected: FAIL — `confidenceColor` not exported yet.

- [ ] **Step 3: Implement**

Add to `frontend/src/features/visualize/colors.ts`:

```typescript
// Sequential single-hue ramp, light -> dark, for confidence_score (0-100).
// Never a rainbow, never reused for anything but a magnitude/confidence
// scale -- see the dataviz skill's color-formula rules. Validate with
// scripts/validate_palette.js before changing these values (see Step 5).
const CONFIDENCE_RAMP = [
  '#C7D2E8',
  '#9FB3D9',
  '#6C8CD5',
  '#3D5FA8',
  '#1F3D7A',
];

export function confidenceColor(score: number): string {
  const index = Math.min(CONFIDENCE_RAMP.length - 1, Math.floor(Math.max(0, score) / 20));
  return CONFIDENCE_RAMP[index];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/colors.test.ts`
Expected: PASS.

- [ ] **Step 5: Validate the ramp**

Run the `dataviz` skill's `scripts/validate_palette.js` against the 5 `CONFIDENCE_RAMP` hex values (in order) for both `--mode light` and `--mode dark`, using this app's real chart-surface colors (check `frontend/src/index.css` for the `--color-surface` values in each theme, same as was done for the sector palette). If anything FAILs, adjust the failing hex value(s) and re-run until both modes pass — then update the `RAMP_ORDER` array literal in this task's own test (Step 1) to match your final values before re-running the test suite, since that test asserts against the literal hex strings.

- [ ] **Step 6: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/visualize/colors.ts frontend/src/features/visualize/colors.test.ts
git commit -m "feat: add validated sequential confidence color ramp"
```

---

### Task 5: Frontend — shared HTML/CSS tree primitive

**Files:**
- Create: `frontend/src/features/visualize/charts/tree/Tree.tsx`
- Test: `frontend/src/features/visualize/charts/tree/Tree.test.tsx`

**Interfaces:**
- Produces: `TreeRoot({ children }): JSX.Element`, `TreeBranch({ label, color?, children }): JSX.Element` (collapsible, default expanded), `TreeLeaf({ ticker, direction, badge?, onClick }): JSX.Element`.
- Consumes: nothing from earlier tasks (pure presentational primitive).

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/visualize/charts/tree/Tree.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { TreeRoot, TreeBranch, TreeLeaf } from './Tree';

describe('TreeBranch', () => {
  it('renders its label and children expanded by default', () => {
    render(
      <TreeRoot>
        <TreeBranch label="Oil & Gas">
          <TreeLeaf ticker="RIL" direction="bullish" onClick={vi.fn()} />
        </TreeBranch>
      </TreeRoot>,
    );
    expect(screen.getByText('Oil & Gas')).toBeInTheDocument();
    expect(screen.getByText('RIL')).toBeInTheDocument();
  });

  it('collapses and re-expands children on click, without unmounting them', async () => {
    render(
      <TreeRoot>
        <TreeBranch label="Oil & Gas">
          <TreeLeaf ticker="RIL" direction="bullish" onClick={vi.fn()} />
        </TreeBranch>
      </TreeRoot>,
    );
    expect(screen.getByText('RIL')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Oil & Gas'));
    expect(screen.queryByText('RIL')).not.toBeInTheDocument();
    await userEvent.click(screen.getByText('Oil & Gas'));
    expect(screen.getByText('RIL')).toBeInTheDocument();
  });

  it('shows a colored dot when a color is given, none when omitted', () => {
    const { container, rerender } = render(
      <TreeRoot>
        <TreeBranch label="Oil & Gas" color="#E85D4C">
          <TreeLeaf ticker="RIL" direction="bullish" onClick={vi.fn()} />
        </TreeBranch>
      </TreeRoot>,
    );
    expect(container.querySelector('[style*="E85D4C"]')).not.toBeNull();

    rerender(
      <TreeRoot>
        <TreeBranch label="Oil & Gas">
          <TreeLeaf ticker="RIL" direction="bullish" onClick={vi.fn()} />
        </TreeBranch>
      </TreeRoot>,
    );
    expect(container.querySelector('[style*="background-color"]')).toBeNull();
  });
});

describe('TreeLeaf', () => {
  it('renders ticker, direction glyph, and an optional badge', () => {
    render(
      <TreeRoot>
        <TreeLeaf ticker="RIL" direction="bearish" badge="72%" onClick={vi.fn()} />
      </TreeRoot>,
    );
    expect(screen.getByText('RIL')).toBeInTheDocument();
    expect(screen.getByText('72%')).toBeInTheDocument();
    expect(screen.getByText('▼')).toBeInTheDocument();
  });

  it('calls onClick when tapped', async () => {
    const onClick = vi.fn();
    render(
      <TreeRoot>
        <TreeLeaf ticker="RIL" direction="bullish" onClick={onClick} />
      </TreeRoot>,
    );
    await userEvent.click(screen.getByText('RIL'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/features/visualize/charts/tree/Tree.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/charts/tree/Tree.tsx`:

```typescript
import { useState, type ReactNode } from 'react';

export function TreeRoot({ children }: { children: ReactNode }) {
  return <ul className="flex flex-col gap-1">{children}</ul>;
}

export function TreeBranch({
  label,
  color,
  children,
}: {
  label: string;
  color?: string;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <li className="border-l-2 border-hairline pl-3">
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        aria-expanded={!collapsed}
        className="flex items-center gap-1.5 py-1 text-xs uppercase tracking-widest text-muted"
      >
        {color && (
          <span aria-hidden="true" className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
        )}
        <span>{label}</span>
        <span aria-hidden="true" className="text-[10px]">
          {collapsed ? '▸' : '▾'}
        </span>
      </button>
      {!collapsed && <ul className="flex flex-col gap-0.5 border-l border-hairline pl-3">{children}</ul>}
    </li>
  );
}

export function TreeLeaf({
  ticker,
  direction,
  badge,
  onClick,
}: {
  ticker: string;
  direction: string;
  badge?: string;
  onClick: () => void;
}) {
  const bullish = direction === 'bullish';
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className="flex w-full items-center gap-2 border-b border-hairline/50 py-1.5 text-left text-sm text-ink last:border-b-0"
      >
        <span aria-hidden="true" className={bullish ? 'text-bullish' : 'text-bearish'}>
          {bullish ? '▲' : '▼'}
        </span>
        <span className="truncate">{ticker}</span>
        {badge && <span className="ml-auto shrink-0 text-xs text-muted">{badge}</span>}
      </button>
    </li>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/features/visualize/charts/tree/Tree.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/tree/Tree.tsx frontend/src/features/visualize/charts/tree/Tree.test.tsx
git commit -m "feat: add shared HTML/CSS tree primitive (TreeRoot/TreeBranch/TreeLeaf)"
```

---

### Task 6: Frontend — `SectorTree` (rebuild, replaces `SectorTreemap`)

**Files:**
- Create: `frontend/src/features/visualize/charts/SectorTree.tsx`
- Test: `frontend/src/features/visualize/charts/SectorTree.test.tsx`
- Delete: `frontend/src/features/visualize/charts/SectorTreemap.tsx`
- Delete: `frontend/src/features/visualize/charts/SectorTreemap.test.tsx`

**Interfaces:**
- Consumes: `groupBySector` (existing, unchanged), `TreeRoot`/`TreeBranch`/`TreeLeaf` (Task 5), `useCompanySelection` (existing, unchanged), `ReasoningPanel` (existing, unchanged).
- Produces: `export default function SectorTree({ companies }: { companies: AlertCompany[] }): JSX.Element`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/charts/SectorTree.test.tsx` (mirrors `SectorTreemap.test.tsx`'s existing structure/fixture/`LanguageProvider` pattern exactly, plus one new collapse test):

```typescript
import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import SectorTree from './SectorTree';
import type { AlertCompany } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

function render(ui: ReactElement) {
  return rtlRender(<LanguageProvider>{ui}</LanguageProvider>);
}

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50', sector: 'oil_gas',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', confidence_score: 50,
    time_horizon: 'Short-Term', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('SectorTree', () => {
  it('renders one branch per sector present, labeled with the human-readable name', () => {
    render(
      <SectorTree
        companies={[
          company({ company_id: 1, sector: 'oil_gas', ticker: 'RIL' }),
          company({ company_id: 2, sector: 'banking', ticker: 'HDFCBANK', direction: 'bearish' }),
        ]}
      />,
    );
    expect(screen.getByText('Oil & Gas')).toBeInTheDocument();
    expect(screen.getByText('Banking')).toBeInTheDocument();
    expect(screen.getByText('RIL')).toBeInTheDocument();
    expect(screen.getByText('HDFCBANK')).toBeInTheDocument();
  });

  it('collapses a sector branch on tap, hiding its companies', async () => {
    render(<SectorTree companies={[company({ company_id: 1, sector: 'oil_gas', ticker: 'RIL' })]} />);
    expect(screen.getByText('RIL')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Oil & Gas'));
    expect(screen.queryByText('RIL')).not.toBeInTheDocument();
  });

  it('expands a ReasoningPanel when a company is tapped', async () => {
    render(<SectorTree companies={[company({ company_id: 1, rationale: 'Refiner margins widen on lower crude.' })]} />);
    await userEvent.click(screen.getByText('AAA'));
    expect(screen.getByText(/Refiner margins widen/)).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<SectorTree companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/SectorTree.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/charts/SectorTree.tsx`:

```typescript
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { groupBySector } from '../transforms';
import { TreeRoot, TreeBranch, TreeLeaf } from './tree/Tree';
import { useCompanySelection } from './useCompanySelection';

export default function SectorTree({ companies }: { companies: AlertCompany[] }) {
  const { toggle, selected } = useCompanySelection(companies);
  const groups = groupBySector(companies);

  if (groups.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      <TreeRoot>
        {groups.map((group) => (
          <TreeBranch key={group.key} label={group.label} color={group.color}>
            {group.companies.map((c) => (
              <TreeLeaf key={c.company_id} ticker={c.ticker} direction={c.direction} onClick={() => toggle(c.company_id)} />
            ))}
          </TreeBranch>
        ))}
      </TreeRoot>
      {selected && <ReasoningPanel company={selected} />}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/SectorTree.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Delete `SectorTreemap`**

```bash
rm frontend/src/features/visualize/charts/SectorTreemap.tsx frontend/src/features/visualize/charts/SectorTreemap.test.tsx
```

Grep for any remaining reference: `grep -rn "SectorTreemap" frontend/src` — should return nothing after Task 10 rewires `AlertChartsPage.tsx` (that happens later in this plan; a reference in `AlertChartsPage.tsx` at this point is expected and gets fixed in Task 10, not this task).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/visualize/charts/SectorTree.tsx frontend/src/features/visualize/charts/SectorTree.test.tsx
git rm frontend/src/features/visualize/charts/SectorTreemap.tsx frontend/src/features/visualize/charts/SectorTreemap.test.tsx
git commit -m "feat: rebuild Sector chart as a real tree (SectorTree replaces SectorTreemap)"
```

Note: the full suite will NOT be green after this commit alone (`AlertChartsPage.tsx` still imports the now-deleted `SectorTreemap` until Task 10) — that's expected for this task; Task 10 fixes it. Do not skip deleting `SectorTreemap` now just to keep the suite green in the interim; the plan's task order handles this.

---

### Task 7: Frontend — `SplitTree` (rebuild, replaces `SplitDonut`)

**Files:**
- Create: `frontend/src/features/visualize/charts/SplitTree.tsx`
- Test: `frontend/src/features/visualize/charts/SplitTree.test.tsx`
- Delete: `frontend/src/features/visualize/charts/SplitDonut.tsx`
- Delete: `frontend/src/features/visualize/charts/SplitDonut.test.tsx`

**Interfaces:**
- Consumes: `rankByMagnitude` (existing), `TreeRoot`/`TreeBranch`/`TreeLeaf` (Task 5), `useCompanySelection`/`ReasoningPanel` (existing).
- Produces: `export default function SplitTree({ companies }: { companies: AlertCompany[] }): JSX.Element`.

Branch labels use "Bullish"/"Bearish" (not the mockup's literal "Positive"/"Negative" wording) — this app uses bullish/bearish terminology consistently everywhere else (`SentimentBar`, `CompanyChip`, every other chart); matching the mockup's STRUCTURE (two branches, ranked companies within each) matters, its exact label text doesn't.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/charts/SplitTree.test.tsx`:

```typescript
import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import SplitTree from './SplitTree';
import type { AlertCompany } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

function render(ui: ReactElement) {
  return rtlRender(<LanguageProvider>{ui}</LanguageProvider>);
}

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', confidence_score: 50,
    time_horizon: 'Short-Term', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('SplitTree', () => {
  it('shows a Bullish and a Bearish branch with the right counts', () => {
    render(
      <SplitTree
        companies={[
          company({ company_id: 1, direction: 'bullish' }),
          company({ company_id: 2, direction: 'bullish', ticker: 'BBB' }),
          company({ company_id: 3, direction: 'bearish', ticker: 'CCC' }),
        ]}
      />,
    );
    expect(screen.getByText('2 Bullish')).toBeInTheDocument();
    expect(screen.getByText('1 Bearish')).toBeInTheDocument();
  });

  it('ranks companies within each branch by magnitude descending', () => {
    render(
      <SplitTree
        companies={[
          company({ company_id: 1, ticker: 'WEAK_BULL', direction: 'bullish', magnitude_low: 1, magnitude_high: 2 }),
          company({ company_id: 2, ticker: 'STRONG_BULL', direction: 'bullish', magnitude_low: 20, magnitude_high: 30 }),
        ]}
      />,
    );
    const items = screen.getAllByRole('button').map((el) => el.textContent || '');
    const strongIdx = items.findIndex((t) => t.includes('STRONG_BULL'));
    const weakIdx = items.findIndex((t) => t.includes('WEAK_BULL'));
    expect(strongIdx).toBeLessThan(weakIdx);
  });

  it('collapses a branch on tap, hiding its companies', async () => {
    render(<SplitTree companies={[company({ company_id: 1, direction: 'bullish' })]} />);
    expect(screen.getByText('AAA')).toBeInTheDocument();
    await userEvent.click(screen.getByText(/Bullish/));
    expect(screen.queryByText('AAA')).not.toBeInTheDocument();
  });

  it('expands a ReasoningPanel when a company is tapped', async () => {
    render(<SplitTree companies={[company({ company_id: 1, rationale: 'Refiner margins widen on lower crude.' })]} />);
    await userEvent.click(screen.getByText('AAA'));
    expect(screen.getByText(/Refiner margins widen/)).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<SplitTree companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/SplitTree.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/charts/SplitTree.tsx`:

```typescript
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { rankByMagnitude } from '../transforms';
import { TreeRoot, TreeBranch, TreeLeaf } from './tree/Tree';
import { useCompanySelection } from './useCompanySelection';

export default function SplitTree({ companies }: { companies: AlertCompany[] }) {
  const { toggle, selected } = useCompanySelection(companies);
  const bullish = rankByMagnitude(companies.filter((c) => c.direction === 'bullish'));
  const bearish = rankByMagnitude(companies.filter((c) => c.direction === 'bearish'));

  if (bullish.length === 0 && bearish.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      <p className="text-xs">
        <span className="text-bullish">{bullish.length} Bullish</span>
        <span className="text-muted"> · </span>
        <span className="text-bearish">{bearish.length} Bearish</span>
      </p>
      <TreeRoot>
        {bullish.length > 0 && (
          <TreeBranch label="Bullish">
            {bullish.map((c) => (
              <TreeLeaf key={c.company_id} ticker={c.ticker} direction={c.direction} onClick={() => toggle(c.company_id)} />
            ))}
          </TreeBranch>
        )}
        {bearish.length > 0 && (
          <TreeBranch label="Bearish">
            {bearish.map((c) => (
              <TreeLeaf key={c.company_id} ticker={c.ticker} direction={c.direction} onClick={() => toggle(c.company_id)} />
            ))}
          </TreeBranch>
        )}
      </TreeRoot>
      {selected && <ReasoningPanel company={selected} />}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/SplitTree.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 5: Delete `SplitDonut`**

```bash
rm frontend/src/features/visualize/charts/SplitDonut.tsx frontend/src/features/visualize/charts/SplitDonut.test.tsx
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/visualize/charts/SplitTree.tsx frontend/src/features/visualize/charts/SplitTree.test.tsx
git rm frontend/src/features/visualize/charts/SplitDonut.tsx frontend/src/features/visualize/charts/SplitDonut.test.tsx
git commit -m "feat: rebuild Split chart as a real tree (SplitTree replaces SplitDonut)"
```

Same note as Task 6: `AlertChartsPage.tsx` still references the deleted `SplitDonut` until Task 10 — expected, not a regression to fix now.

---

### Task 8: Frontend — `ConfidenceTree` (new)

**Files:**
- Create: `frontend/src/features/visualize/charts/ConfidenceTree.tsx`
- Test: `frontend/src/features/visualize/charts/ConfidenceTree.test.tsx`

**Interfaces:**
- Consumes: `rankByConfidence` (Task 3), `confidenceColor` (Task 4), `TreeRoot`/`TreeLeaf` (Task 5, no `TreeBranch` — this tree is a flat ranked list, matching the mockup's shape exactly, no sector/direction grouping), `useCompanySelection`/`ReasoningPanel` (existing).
- Produces: `export default function ConfidenceTree({ companies }: { companies: AlertCompany[] }): JSX.Element`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/charts/ConfidenceTree.test.tsx`:

```typescript
import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import ConfidenceTree from './ConfidenceTree';
import type { AlertCompany } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

function render(ui: ReactElement) {
  return rtlRender(<LanguageProvider>{ui}</LanguageProvider>);
}

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', confidence_score: 50,
    time_horizon: 'Short-Term', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('ConfidenceTree', () => {
  it('lists every company with its confidence_score as a percentage badge', () => {
    render(
      <ConfidenceTree
        companies={[
          company({ company_id: 1, ticker: 'NVDA', confidence_score: 98 }),
          company({ company_id: 2, ticker: 'AMD', confidence_score: 91 }),
        ]}
      />,
    );
    expect(screen.getByText('98%')).toBeInTheDocument();
    expect(screen.getByText('91%')).toBeInTheDocument();
  });

  it('orders companies by confidence_score descending', () => {
    render(
      <ConfidenceTree
        companies={[
          company({ company_id: 1, ticker: 'LOW', confidence_score: 42 }),
          company({ company_id: 2, ticker: 'HIGH', confidence_score: 96 }),
        ]}
      />,
    );
    const items = screen.getAllByRole('button').map((el) => el.textContent || '');
    expect(items.findIndex((t) => t.includes('HIGH'))).toBeLessThan(items.findIndex((t) => t.includes('LOW')));
  });

  it('expands a ReasoningPanel when a company is tapped', async () => {
    render(<ConfidenceTree companies={[company({ company_id: 1, rationale: 'Refiner margins widen on lower crude.' })]} />);
    await userEvent.click(screen.getByText('AAA'));
    expect(screen.getByText(/Refiner margins widen/)).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<ConfidenceTree companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/ConfidenceTree.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/charts/ConfidenceTree.tsx`:

```typescript
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { confidenceColor } from '../colors';
import { rankByConfidence } from '../transforms';
import { TreeRoot, TreeLeaf } from './tree/Tree';
import { useCompanySelection } from './useCompanySelection';

export default function ConfidenceTree({ companies }: { companies: AlertCompany[] }) {
  const { toggle, selected } = useCompanySelection(companies);
  const ranked = rankByConfidence(companies);

  if (ranked.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      <TreeRoot>
        {ranked.map((c) => (
          <TreeLeaf
            key={c.company_id}
            ticker={c.ticker}
            direction={c.direction}
            badge={`${c.confidence_score}%`}
            onClick={() => toggle(c.company_id)}
          />
        ))}
      </TreeRoot>
      {selected && <ReasoningPanel company={selected} />}
    </div>
  );
}
```

Note: `confidenceColor` is imported but not yet visually applied to anything in this minimal version — `TreeLeaf` doesn't currently accept a badge color override. If you want the badge itself colored by `confidenceColor(c.confidence_score)`, that requires a small addition to `TreeLeaf` (a `badgeColor?: string` prop applied as an inline `style` on the badge `<span>`) — make that addition here if you do, and add one test asserting the badge's color reflects a high vs. low score differently. This is left to your judgment as a visual nicety, not a strict requirement — the flat ranked list with a plain-text `NN%` badge already satisfies the spec's core requirement.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/ConfidenceTree.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/ConfidenceTree.tsx frontend/src/features/visualize/charts/ConfidenceTree.test.tsx
git commit -m "feat: add ConfidenceTree chart"
```

---

### Task 9: Frontend — `TimelineTree` (new)

**Files:**
- Create: `frontend/src/features/visualize/charts/TimelineTree.tsx`
- Test: `frontend/src/features/visualize/charts/TimelineTree.test.tsx`

**Interfaces:**
- Consumes: `groupByTimeHorizon` (Task 3), `TreeRoot`/`TreeBranch`/`TreeLeaf` (Task 5), `useCompanySelection`/`ReasoningPanel` (existing).
- Produces: `export default function TimelineTree({ companies }: { companies: AlertCompany[] }): JSX.Element`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/charts/TimelineTree.test.tsx`:

```typescript
import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import TimelineTree from './TimelineTree';
import type { AlertCompany } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

function render(ui: ReactElement) {
  return rtlRender(<LanguageProvider>{ui}</LanguageProvider>);
}

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', confidence_score: 50,
    time_horizon: 'Short-Term', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('TimelineTree', () => {
  it('renders one branch per horizon present, in fixed chronological order', () => {
    render(
      <TimelineTree
        companies={[
          company({ company_id: 1, ticker: 'LONG', time_horizon: 'Long-Term' }),
          company({ company_id: 2, ticker: 'NOW', time_horizon: 'Immediate' }),
        ]}
      />,
    );
    const branches = screen.getAllByRole('button', { expanded: true }).map((el) => el.textContent || '');
    const immediateIdx = branches.findIndex((t) => t.includes('Immediate'));
    const longIdx = branches.findIndex((t) => t.includes('Long-Term'));
    expect(immediateIdx).toBeGreaterThanOrEqual(0);
    expect(longIdx).toBeGreaterThan(immediateIdx);
    expect(screen.getByText('LONG')).toBeInTheDocument();
    expect(screen.getByText('NOW')).toBeInTheDocument();
  });

  it('collapses a horizon branch on tap, hiding its companies', async () => {
    render(<TimelineTree companies={[company({ company_id: 1, time_horizon: 'Immediate' })]} />);
    expect(screen.getByText('AAA')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Immediate'));
    expect(screen.queryByText('AAA')).not.toBeInTheDocument();
  });

  it('expands a ReasoningPanel when a company is tapped', async () => {
    render(<TimelineTree companies={[company({ company_id: 1, rationale: 'Refiner margins widen on lower crude.' })]} />);
    await userEvent.click(screen.getByText('AAA'));
    expect(screen.getByText(/Refiner margins widen/)).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<TimelineTree companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/TimelineTree.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/charts/TimelineTree.tsx`:

```typescript
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { groupByTimeHorizon } from '../transforms';
import { TreeRoot, TreeBranch, TreeLeaf } from './tree/Tree';
import { useCompanySelection } from './useCompanySelection';

export default function TimelineTree({ companies }: { companies: AlertCompany[] }) {
  const { toggle, selected } = useCompanySelection(companies);
  const groups = groupByTimeHorizon(companies);

  if (groups.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      <TreeRoot>
        {groups.map((group) => (
          <TreeBranch key={group.key} label={group.label}>
            {group.companies.map((c) => (
              <TreeLeaf key={c.company_id} ticker={c.ticker} direction={c.direction} onClick={() => toggle(c.company_id)} />
            ))}
          </TreeBranch>
        ))}
      </TreeRoot>
      {selected && <ReasoningPanel company={selected} />}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/TimelineTree.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/TimelineTree.tsx frontend/src/features/visualize/charts/TimelineTree.test.tsx
git commit -m "feat: add TimelineTree chart"
```

---

### Task 10: Frontend — page integration: 6-chart pager + Normal/Drilldown toggle

**Files:**
- Modify: `frontend/src/pages/AlertChartsPage.tsx`
- Modify: `frontend/src/pages/AlertChartsPage.test.tsx`

**Interfaces:**
- Consumes: `SectorTree` (Task 6), `SplitTree` (Task 7), `ConfidenceTree` (Task 8), `TimelineTree` (Task 9), `TierRows`/`ImpactBar` (existing, unchanged).
- Produces: `AlertChartsPage` renders 6 chart types via its pager, plus a Normal/Drilldown toggle that filters `alert.companies` (by `basis === 'direct_mention'`) before handing it to whichever chart is active.

- [ ] **Step 1: Read the current file first**

Read `frontend/src/pages/AlertChartsPage.tsx` and `frontend/src/pages/AlertChartsPage.test.tsx` in full before editing — this file may have drifted since this plan was written (other concurrent sessions may have touched shared UI files). Adapt the edit below to the file as it actually is; the INTENT (6-entry `CHARTS` array, page-level breadth toggle, filtered companies passed to the active chart) is what matters, not matching this plan's exact line numbers.

- [ ] **Step 2: Update the `CHARTS` array and imports**

Replace the imports for `SectorTreemap`/`SplitDonut` with `SectorTree`/`SplitTree`, add imports for `ConfidenceTree`/`TimelineTree`, and update the `CHARTS` array:

```typescript
import SectorTree from '../features/visualize/charts/SectorTree';
import TierRows from '../features/visualize/charts/TierRows';
import ImpactBar from '../features/visualize/charts/ImpactBar';
import SplitTree from '../features/visualize/charts/SplitTree';
import ConfidenceTree from '../features/visualize/charts/ConfidenceTree';
import TimelineTree from '../features/visualize/charts/TimelineTree';

const CHARTS = [
  { key: 'sector', label: 'Sector', Component: SectorTree },
  { key: 'tier', label: 'Tier', Component: TierRows },
  { key: 'impact', label: 'Impact', Component: ImpactBar },
  { key: 'split', label: 'Split', Component: SplitTree },
  { key: 'confidence', label: 'Confidence', Component: ConfidenceTree },
  { key: 'timeline', label: 'Timeline', Component: TimelineTree },
] as const;
```

- [ ] **Step 3: Add the breadth toggle**

Add state and a filtered-companies computation, then a toggle control in the header row (alongside the existing back button/title), and pass the filtered array to the active chart instead of `alert.companies` directly:

```typescript
type Breadth = 'normal' | 'drilldown';

// ...inside the component:
const [breadth, setBreadth] = useState<Breadth>('normal');
const visibleCompanies =
  breadth === 'normal' ? alert.companies.filter((c) => c.basis === 'direct_mention') : alert.companies;
```

Render the toggle (a simple two-button group, matching the existing pager tab styling conventions already in this file):

```tsx
<div className="flex gap-1 self-start rounded-md border border-hairline bg-surface p-0.5">
  {(['normal', 'drilldown'] as Breadth[]).map((mode) => (
    <button
      key={mode}
      type="button"
      onClick={() => setBreadth(mode)}
      className={`rounded px-2 py-0.5 text-[11px] uppercase tracking-widest ${
        breadth === mode ? 'bg-page text-ink' : 'text-muted'
      }`}
    >
      {mode === 'normal' ? 'Normal' : 'Drilldown'}
    </button>
  ))}
</div>
```

Where the active chart is rendered, pass `visibleCompanies` instead of `alert.companies`:

```tsx
{visibleCompanies.length === 0 ? (
  <p className="p-4 text-xs uppercase tracking-widest text-muted">
    No directly-confirmed companies for this alert — try Drilldown for the wider sector picture.
  </p>
) : (
  <Component companies={visibleCompanies} />
)}
```

- [ ] **Step 4: Update the test file**

Read the current `AlertChartsPage.test.tsx` fully first (per Step 1) to match its actual mocking conventions, then add/update tests:
- Pager labels: assert all 6 labels present (`Sector`, `Tier`, `Impact`, `Split`, `Confidence`, `Timeline`), not just 4.
- Breadth toggle: with a fixture alert containing one `direct_mention` and one `sector_inference` company, assert Normal view shows only the direct one, clicking "Drilldown" reveals the sector-inferred one too.
- Empty-Normal-view: with a fixture alert where every company is `sector_inference`, assert the "No directly-confirmed companies..." message appears in Normal view.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/AlertChartsPage.test.tsx`
Expected: PASS.

- [ ] **Step 6: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all tests pass, including Tasks 6/7's now-resolved dangling references (grep `SectorTreemap`/`SplitDonut` across `frontend/src` — should return nothing).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/AlertChartsPage.tsx frontend/src/pages/AlertChartsPage.test.tsx
git commit -m "feat: wire 6-chart pager and Normal/Drilldown breadth toggle into AlertChartsPage"
```

---

### Task 11: Frontend — regression tests for `ImpactBar`/`TierRows` against >5 companies

**Files:**
- Modify: `frontend/src/features/visualize/charts/ImpactBar.test.tsx`
- Modify: `frontend/src/features/visualize/charts/TierRows.test.tsx`

**Interfaces:**
- Consumes: `ImpactBar`, `TierRows` (existing, unchanged in this task — this task only adds test coverage confirming they still behave correctly once the backend no longer caps company count at 5).

- [ ] **Step 1: Add an 8-company regression test to `ImpactBar.test.tsx`**

Read the current file first, then add:

```typescript
it('renders correctly with more than 5 companies (the cap was removed in this plan)', () => {
  const eight = Array.from({ length: 8 }, (_, i) =>
    company({
      company_id: i + 1,
      ticker: `CO${i}`,
      direction: i % 2 === 0 ? 'bullish' : 'bearish',
      magnitude_low: i,
      magnitude_high: i + 1,
    }),
  );
  render(<ImpactBar companies={eight} />);
  eight.forEach((c) => expect(screen.getByText(c.ticker)).toBeInTheDocument());
});
```

- [ ] **Step 2: Add the equivalent to `TierRows.test.tsx`**

```typescript
it('renders correctly with more than 5 companies across tiers (the cap was removed in this plan)', () => {
  const tiers = ['NIFTY50', 'NIFTYNEXT50', 'NIFTYMIDCAP150', 'NIFTYSMALLCAP250'];
  const eight = Array.from({ length: 8 }, (_, i) =>
    company({ company_id: i + 1, ticker: `CO${i}`, index_tier: tiers[i % tiers.length] }),
  );
  render(<TierRows companies={eight} />);
  eight.forEach((c) => expect(screen.getByText(c.ticker)).toBeInTheDocument());
});
```

- [ ] **Step 3: Run both test files**

Run: `cd frontend && npx vitest run src/features/visualize/charts/ImpactBar.test.tsx src/features/visualize/charts/TierRows.test.tsx`
Expected: PASS. If either fails (e.g. `ImpactBar`'s fixed-pixel bar-width tuning from the prior plan visually degrades badly at 8 items — the assertions above only check that all tickers render, not that bars stay visually distinct), that's a real finding: note it and consider whether `ImpactBar`'s `MAX_BAR_PX`/`MIN_BAR_PX` constants (tuned for ≤5 items at a 390px viewport) need adjustment for higher counts. Fix if the test reveals a genuine rendering break (e.g. a crash or nothing rendering); if it's a visual-density concern rather than a functional break, flag it for Task 12's visual verification pass rather than guessing at a fix here.

- [ ] **Step 4: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/ImpactBar.test.tsx frontend/src/features/visualize/charts/TierRows.test.tsx
git commit -m "test: add >5-company regression coverage for ImpactBar/TierRows"
```

---

### Task 12: Palette validation + visual verification

**Files:** none (verification-only task, following the same pattern as the prior charts-page plan's final task)

- [ ] **Step 1: Confirm the confidence ramp validated clean**

If Task 4's Step 5 validation wasn't already fully clean (all checks PASS, no unresolved WARN), re-run `scripts/validate_palette.js` now against the final `CONFIDENCE_RAMP` values and fix/re-commit before proceeding.

- [ ] **Step 2: Seed rich test data**

Start isolated backend/frontend dev servers (same pattern as the prior plan's Task 13 — unique ports, a local sqlite copy). Seed test alerts covering:
- An alert with 8+ companies across multiple sectors, multiple time horizons, and a wide confidence spread (10-95), for stress-testing all 6 charts at a higher count than the old 5-cap ever allowed.
- An alert where every company is `sector_inference` (tests the empty-Normal-view message).
- An alert with only 1 company (edge case, matches the prior plan's single-company check).

- [ ] **Step 3: Playwright visual verification**

Using the Playwright MCP tools, verify for all 6 chart types, in both light and dark theme, at mobile (390px) and desktop widths:
- Sector Tree: branches show the right sector colors, expand/collapse works, long sector lists scroll cleanly rather than overflowing.
- Split Tree: Bullish/Bearish branches show correct counts and ranking; the kept count-summary line reads correctly.
- Confidence Tree: companies ranked correctly, `NN%` badges legible in both themes.
- Timeline Tree: horizon branches in correct chronological order, expand/collapse works.
- Tier/Impact (unchanged components): still render correctly with the 8-company fixture — this is where Task 11's flagged "visual density" concern (if any) gets resolved for real, by eye, not by test assertion.
- Normal/Drilldown toggle: switching breadth visibly changes company counts per chart, persists correctly when swiping between chart types.
- Tap-to-expand `ReasoningPanel` still works in every tree.

Take screenshots at each checkpoint. Do not report this feature as visually complete without this step.

- [ ] **Step 4: Fix any visual issues found, then re-verify**

Iterate Steps 2-3 until clean, committing fixes as they're made — following the same "measure, don't guess, verify the fix" discipline used throughout the prior charts-page plan (e.g. the `ImpactBar` zero-width-bar bug was only found this way).

---

## Execution Handoff

After all 12 tasks are complete and verified, use **superpowers:finishing-a-development-branch** to merge/push per the user's choice.
