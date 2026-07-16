# Reasoning Engine Upgrade — Design

## Goal

NewsFlo's competitive positioning depends on the quality and defensibility of its
AI analysis, not just on having AI analysis. This design upgrades the current
single-call, LLM-self-rated pipeline into a staged, evidence-disciplined,
deterministically-scored reasoning engine — while explicitly deferring the
knowledge-graph/vector-DB/RAG/monorepo rebuild proposed by an external
architecture document (`ai_reasoning_pipeline/` in Downloads) that assumed a
greenfield project. That document's real value — a domain reasoning rulebook,
sector playbooks, a deterministic confidence formula, and an evidence-discipline
model — is mined into this design; its assumption of starting from zero is not.

The intended moat is not the prompt or the rulebook (both are learnable by a
competitor). It is the **outcome-calibration flywheel**: every analysis gets
checked against what the stock actually did afterward, and that accumulated,
user-flow-specific prediction-vs-reality dataset compounds over time in a way a
later entrant cannot backfill. This design's central requirement is that every
new piece of reasoning quality (rulebook rules, confidence weights, hypothesis
generation) is wired to feed and be corrected by that flywheel, not bolted on as
a one-off prompt improvement.

Scope: solo developer + Claude Code, ship fast. No manual company-knowledge
curation (500+ YAML profiles), no knowledge graph, no vector DB, no monorepo/
TypeScript rewrite, no task queue. Everything below extends the existing
FastAPI/SQLAlchemy/Postgres app in place.

## Current pipeline (grounded in the actual code)

`backend/app/pipeline.py::process_new_articles`, scheduled from
`scheduler.py::_run_ingestion_and_analysis`, runs today as:

1. `filtering/heuristic.py::filter_new_articles` — pure keyword/regex classifier
   over 5 `CATEGORY_KEYWORDS` buckets (`oil_energy`, `banking`, `auto_ev`,
   `geopolitics`, `market_news` — the last a ~28-keyword catch-all), first-match-
   wins by dict order. Sets `Article.status` to `FILTERED` or `CATEGORIZED`.
2. Dedup: `_find_reusable_alert` reuses a same-title alert within 24h, skipping
   the LLM call entirely.
3. `analysis/claude_client.py::analyze_article` — **one** LLM call (Claude Sonnet
   4.5 primary, Groq llama-3.3-70b-versatile → llama-3.1-8b-instant fallback on
   rate limit) using the `record_analysis` tool. `SYSTEM_PROMPT` casts the model
   as a senior equity analyst; `ANALYSIS_INSTRUCTIONS` is a static 10-rule block.
   The model returns `category` + a `companies[]` array where each entry
   self-reports `direction`, `magnitude_low/high`, `rationale`, `key_points[]`,
   `confidence_score` (0-100, **LLM self-rated**), and `time_horizon`. Sector must
   match one of 10 `SECTOR_DEFINITIONS` (a *different*, more granular taxonomy
   than the 5-bucket filtering categories above).
4. `companies/resolution.py::resolve_companies` — deterministic ticker/exact-name/
   single-substring-match resolution; sector-inference mentions expand to the
   top-5 companies in that sector by index tier. No fuzzy or embedding matching.
5. `_persist_alert` — for each resolved company, calls
   `calibration/blender.py::get_calibrated_magnitude(session, category,
   company_id)`, which — **only once ≥5 `CalibrationSample` rows exist** for that
   exact `(category, company_id)` pair — overrides `magnitude_low/high` with
   `mean ± population_stdev` of actual past outcomes and flips
   `AlertCompany.confidence` from `"llm_estimate"` to `"calibrated"`. Note: this
   *never touches `confidence_score`* today — that field stays whatever the LLM
   self-rated, always.
6. The outcome side of the loop **already exists and already runs**:
   `outcomes/tracker.py::check_pending_outcomes`, scheduled per horizon (1, 3, 7
   days) hourly, fetches real price moves via `yfinance`
   (`outcomes/price_fetcher.py`) and writes `CalibrationSample` rows. This is the
   seed of the flywheel this design formalizes and extends — it is not being
   built from scratch.

Two taxonomies matter and must not be conflated: the 5-bucket **filtering
category** (coarse, used for ingestion filtering + calibration keying +
`Article.category`) and the 10-value **sector** (used for company resolution and
sector-inference fan-out). New event-type classification introduced below is a
third, additive concept — it does not replace either.

## What changes

### 1. Two-call pipeline instead of one

`analyze_article` splits into two sequential Claude calls inside
`analysis/claude_client.py`:

- **Call A — event classification** (small, cheap, `temperature≈0`): takes
  title+content, returns a structured event (`event_type` from a fixed taxonomy
  drawn from the rulebook — e.g. `REPO_RATE_CHANGE`, `EARNINGS_BEAT`,
  `COMMODITY_SHOCK`, `CURRENCY_MOVE`, `CORPORATE_ACTION`, `REGULATION`,
  `GEOPOLITICAL`, `OTHER`), `direction` (increase/decrease/neutral), and the
  existing `category`/sector-relevant signal. This reuses the existing
  `record_analysis`-style tool-call mechanism, just a second, smaller tool.
- **Call B — cognitive reasoning** (the existing analyst call, restructured):
  receives Call A's classified event plus a rulebook/playbook excerpt selected
  by `event_type`/sector (see below), plus this company's calibration summary
  (sample count, historical mean/stdev, hit-rate) pulled from
  `calibration/blender.py` where available. Produces the existing fields
  (`direction`, `magnitude_low/high`, `time_horizon`) plus new required fields:
  `reasons: list[str]`, `alternative_hypothesis: str`, `risks: list[str]`,
  `assumptions: list[str]`, `unknowns: list[str]`, and `evidence_refs:
  list[str]` (each reason/claim must cite something: a quoted fact from the
  article, a named historical analog, or a rulebook rule ID — enforced by
  validation, see Evidence discipline below). `confidence_score` is **removed
  from the tool schema** — Call B no longer self-rates; the Confidence Engine
  computes it deterministically after the call.

Total added latency: one extra small Claude call (~1-2s at low token count),
still comfortably inside the existing 10s target. Cost impact: roughly 1.3-1.5x
per article (Call A is short), acceptable at "thousands of articles/day" scale.

### 2. Domain rulebook + sector playbooks as static data (zero infra)

New module `backend/app/reasoning/rulebook.py` and `playbooks.py`: the
`FINANCIAL_REASONING_RULEBOOK`, `SECTOR_PLAYBOOKS`, and
`ECONOMIC_PROPAGATION_RULEBOOK` content (from the brainstormed docs) becomes
Python dicts keyed by `event_type` and by the existing 10-value `sector` enum —
not a database, not a graph, not YAML files loaded at boot (that's a possible
later refinement, not needed for v1). A lookup function
`select_context(event_type, sector) -> str` returns the relevant excerpt to
inject into Call B's prompt. Each rule gets a stable short ID (e.g.
`RULE_REPO_CUT_BANKING`) so Call B's `evidence_refs` can cite it directly.

### 3. Deterministic Confidence Engine

New `backend/app/reasoning/confidence.py`, implementing a weighted formula
(adapted from the brainstormed `SPEC_10`, but with inputs grounded in data that
actually exists today):

| Component | Weight | Source |
|---|---|---|
| Historical calibration | 30% | `CalibrationSample` stats for this `(category, company_id)` — sample count *and* variance, not just presence; 0 if <5 samples (matches existing `CALIBRATION_SAMPLE_THRESHOLD`) |
| Evidence completeness | 20% | count/coverage of `evidence_refs` vs. claims made in Call B's output |
| Rulebook match strength | 20% | whether a rulebook rule matched this `event_type`+sector directly, vs. generic/no match (this is the stand-in for "knowledge graph strength" — no graph needed) |
| Source credibility | 10% | static per-source score (new small config table/dict) |
| Reasoning consistency | 10% | schema validation pass, contradiction flags (e.g. Call B flags conflicting evidence itself) |
| Data freshness | 10% | article age at analysis time |

Output: `confidence_score` (0-100, replacing the LLM self-rating),
`confidence_band` (LOW/MODERATE/HIGH/VERY_HIGH, same bands as the brainstormed
spec), plus `confidence_contributors: list[str]` and `confidence_penalties:
list[str]` for UI display ("+ Strong historical calibration (12 samples)", "-
No rulebook match, generic reasoning only"). Weights live in
`config.py`-level constants, not hardcoded, so they can be retuned later from
calibration health data without a code change to the pipeline itself.

This is the highest-leverage change: it turns confidence from "the model said
so" into something computed from evidence the user (and a regulator, eventually)
can inspect.

### 4. Evidence discipline

Call B's `evidence_refs` are validated post-call: every entry in `reasons[]`
should be traceable to an `evidence_refs` entry (quoted article text, "historical:
<company/event>", or a rulebook rule ID). Claims that fail this check are not
silently dropped (v1 doesn't have the infrastructure for a repair-prompt loop)
— they're flagged with a lower per-claim confidence contribution and logged for
later prompt tuning. Storage: `AlertCompany` gains new nullable columns (see
Data model below) instead of overloading `rationale`/`key_points_json`, so the
existing fields keep working for anything not yet migrated to the new shape and
the frontend can be updated incrementally, screen by screen.

### 5. Calibration flywheel extension (the actual moat)

The 1/3/7-day outcome loop already exists (`outcomes/tracker.py`,
`calibration/blender.py`) and does not need to be rebuilt. It's extended in two
ways:

- `blender.py` gains a second function, `get_calibration_health(category,
  company_id) -> {sample_count, hit_rate, mean_error}`, used by the Confidence
  Engine's "historical calibration" component (today `blender.py` only exposes
  a magnitude blend, not a confidence-relevant summary).
- A new lightweight aggregate — `rulebook_id` gets logged on every
  `AlertCompany` (which rule, if any, matched) so that, over time, a query can
  answer "which rulebook rules are actually well-calibrated vs. overconfident,"
  informing manual rule and weight tuning later. This is deliberately just a
  logged column + a query, not a new service — matches the "ship fast" scope.

### 6. Data model changes

`AlertCompany` gains (manual `_ADDED_COLUMNS`-style ALTER, matching the
existing migration pattern in `db.py` — introducing Alembic is explicitly out
of scope for this pass):

- `event_type: String, nullable` — Call A's classification
- `reasons_json`, `risks_json`, `assumptions_json`, `unknowns_json`,
  `evidence_refs_json: Text, nullable` — mirrors the existing
  `key_points_json` pattern
- `alternative_hypothesis: Text, nullable`
- `confidence_band: String, nullable`
- `confidence_contributors_json`, `confidence_penalties_json: Text, nullable`
- `rulebook_id: String, nullable`
- `prompt_version`, `knowledge_version: String, nullable`

`confidence_score` (existing column) stays, now populated by the Confidence
Engine instead of the LLM. `confidence` (existing `llm_estimate|calibrated`
flag) stays as-is, describing magnitude blending specifically.

### 7. Versioning (lightweight)

`ANALYSIS_INSTRUCTIONS`, the rulebook dicts, and the confidence weight table
each get a version string constant, git-tracked (no separate prompt-registry
service). `prompt_version` + `knowledge_version` are stamped on every
`AlertCompany` row at persist time, so any future analysis can be traced back
to exactly which prompt/rulebook version produced it — enough for debugging and
eventual A/B comparison without building the full evaluation-suite/registry
infrastructure from the brainstormed docs.

### 8. API / UI

`routers/alerts.py::_serialize_alert` adds the new fields to the per-company
response dict (additive, existing consumers unaffected). Frontend consumption
(splitting the existing rationale display into Facts/Evidence/Reasoning/Risks/
Confidence-explanation sections, extending the already-built `ConfidenceTree`)
is **out of scope for this design** — it's a separate, focused frontend design
once the backend shape is real and stable.

## Explicitly deferred

- Knowledge graph / graph database (relational or Neo4j)
- Vector DB / embeddings / RAG (pgvector included — revisit only if historical
  retrieval quality genuinely suffers without it)
- Manual company knowledge base (500+ YAML profiles, Nifty50→500 sequencing)
- Task queue / worker infrastructure (APScheduler remains sufficient at current
  article volume)
- Prompt-registry microservice, full evaluation suite / gold dataset, CI
  regression gates — a lighter version (version stamping) ships now; the full
  benchmark harness is future work once there's enough analysis volume to make
  a gold dataset meaningful
- Monorepo / TypeScript backend rewrite
- Multi-model ensemble / cross-validation between providers
- Portfolio simulator, scenario simulator, and all "enterprise" phase features

## Testing

Existing test coverage pattern (near-1:1 test files per module, per the earlier
codebase survey) extends naturally: unit tests for `rulebook.select_context`,
`confidence.compute_score` (deterministic — pure function, easy to test with
fixed inputs), and `blender.get_calibration_health`. Integration test for the
two-call pipeline using recorded/mocked Claude responses, following whatever
mocking pattern `test_claude_client` (or equivalent) already uses for the
single-call version today.
