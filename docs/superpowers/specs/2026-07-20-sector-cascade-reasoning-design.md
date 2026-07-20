# Sector-Cascade Reasoning — Design

## Goal

This is sub-project 3 of the larger insights-pipeline roadmap (sub-project 1,
full article text fetching, shipped `2026-07-18`; sub-project 2, relevance
filter rework, shipped `2026-07-20`). It implements the core of the
originally-requested pipeline: news -> facts -> probable affected sectors ->
companies per sector -> cascade to secondary/tertiary sectors -> companies
per cascade sector, with both positive and negative direction captured per
company, in plain language a non-investor can follow.

## Current state (grounded in the actual code)

- `analyze_article()` (`app/analysis/claude_client.py:540-583`) already
  returns direct companies plus up to 3 `indirect_l1` and 2 `indirect_l2`
  entries per article, each tagged `direction` (bullish/bearish),
  `impact_level`, `parent_ticker` -- but all of this comes out of a **single**
  LLM call driven by one ~170-line mega-prompt (`ANALYSIS_INSTRUCTIONS`).
  There is no genuine sequential reasoning today: the model free-associates
  companies and their sector/impact-level/parent all at once, company-first
  rather than sector-first.
- `AlertCompany` (`app/models.py:79-133`) already persists `impact_level`
  and `parent_company_id`, with a per-hop confidence discount
  (`LEVEL_CONFIDENCE_MULTIPLIER`, `app/pipeline.py:38`:
  `direct:1.0, indirect_l1:0.7, indirect_l2:0.45`). This sub-project reuses
  that schema unchanged -- it does not need new columns or tables.
- `resolve_companies` (`app/companies/resolution.py`) matches the LLM's
  free-text company mentions against the `Company` DB table by
  ticker/name; company knowledge comes from the LLM's own training data,
  not a fixed list it's constrained to. Any mention that doesn't match an
  existing `Company` row is silently dropped (existing "omit rather than
  mismatch" convention).
- `SECTORS` (`app/analysis/schemas.py:5`) is a closed 9-value taxonomy
  (`oil_gas, banking, auto, it, pharma, fmcg, metals, telecom, infra`) plus
  `other`. The local `Company` DB has 1007 rows; 182 already sit in `other`.
  Nothing in the current taxonomy cleanly covers railways, real estate,
  defense, agriculture, consumer durables, media, chemicals, or textiles --
  the kind of sectors the "all types of financial news" goal (government
  infrastructure spending, contract wins, policy changes) actually touches.
- `SUB_SECTOR_TAXONOMY` / `classify_batch` (`app/companies/sub_sectors.py`)
  already establish the exact reusable pattern for a one-time,
  tool-forced, batched LLM reclassification job with fallback-model retry
  on rate limit (see `backfill_subsectors.py`) -- this sub-project's
  backfill reuses that pattern for top-level `Company.sector`, not
  sub-sector.
- The frontend Impact Tree chart does **not** currently walk
  `parent_company_id` at all (a separate, already-known gap, out of scope
  here) -- it buckets by `sector`/`sub_sector` instead. This sub-project
  does not touch the frontend; it only makes the underlying data more
  accurate, which the Impact Tree already displays via its existing
  sector/sub-sector bucketing.

## Design

### 1. Sector taxonomy expansion

Add to `SECTORS` (`app/analysis/schemas.py`): `railways_transport`,
`construction_realestate`, `defense`, `agriculture`, `consumer_durables`,
`media_entertainment`, `chemicals`, `textiles`. Each gets an `_other`
fallback value, matching every existing sector's convention. No
sub-sector taxonomy is added for these yet (matches the existing
convention that `other` has none either -- `Company.sub_sector` stays
`NULL` for companies in a sector with no taxonomy, which the frontend
already renders as an unbucketed flat list, not an error). `healthcare` is
deliberately not added -- hospitals/diagnostics already sit under
`pharma`'s `hospital_diagnostics` sub-sector.

### 2. One-time company re-tagging backfill

New script `backend/backfill_sectors.py`, following
`backfill_subsectors.py`'s exact structure: batch all 1007 `Company` rows
(not just the 182 in `other` -- some may be mistagged into an existing
sector too) through a `classify_batch`-style tool-forced call against the
*expanded* `SECTORS` enum, `MODEL` with `FALLBACK_MODEL` fallback on rate
limit, "omit rather than mismatch" (a company the model doesn't address is
left untouched, not guessed). Writes back `Company.sector`; does not touch
`Company.sub_sector` (a separate, later concern if the new sectors ever
grow sub-sector taxonomies).

### 3. Seven-stage reasoning pipeline

New file `app/analysis/cascade.py`. Replaces the internals of
`analyze_article`'s single mega-prompt with 7 sequential
`client.chat.completions.create` calls, each tool-forced for structured
output (same discipline as today's `RECORD_ANALYSIS_TOOL` /
`classify_batch`'s tool schemas), threading context forward through the
chain:

1. **Fact & mechanism extraction** -- input: title + `article_text()`.
   Output: plain-text facts/mechanism summary (what happened, key
   entities/numbers, the economic mechanism). Not persisted; feeds every
   later stage's prompt as context. Model: `FALLBACK_MODEL`.
2. **Primary sector identification** -- input: facts. Output: list of
   directly-affected sectors (from the expanded `SECTORS` enum), each with
   a sector-level `direction` and a one-line mechanism ("why this
   sector"). Model: `FALLBACK_MODEL`.
3. **Primary companies** -- input: facts + primary sectors. Output:
   companies per primary sector -- both positively and negatively affected
   where applicable (a single sector can have winners and losers from the
   same news) -- each with the full existing `CompanyMention` field set
   (`direction`, `magnitude_low/high`, `rationale`, `key_points`,
   `confidence_score`, `time_horizon`, `reasons`, `evidence_refs`,
   `risks`, `assumptions`, `unknowns`, `alternative_hypothesis`),
   `impact_level="direct"`, `parent_ticker=None`. Model: `MODEL` (primary
   model -- this is the user-facing rationale/key_points text, the exact
   thing this session's earlier prompt-quality work targeted).
4. **Cascade sectors, hop 1** -- input: facts + primary sectors. Output:
   secondary sectors rippling from the primary ones, each tagged with
   which primary sector triggered it, direction, one-line mechanism.
   Model: `FALLBACK_MODEL`.
5. **Cascade companies, hop 1** -- input: facts + hop-1 sectors + primary
   companies. Output: companies per hop-1 sector, each tagged
   `parent_ticker` (the specific primary company it's chained from, from
   stage 3's output), `impact_level="indirect_l1"`. Model: `MODEL`.
6. **Cascade sectors, hop 2** -- input: facts + hop-1 sectors. Output:
   tertiary sectors rippling from hop-1. Model: `FALLBACK_MODEL`.
7. **Cascade companies, hop 2** -- input: facts + hop-2 sectors + hop-1
   companies. Output: companies per hop-2 sector, `parent_ticker` from a
   hop-1 company (stage 5's output), `impact_level="indirect_l2"`. Model:
   `MODEL`.

7 Groq calls per article (4 `FALLBACK_MODEL`, 3 `MODEL`), up from 1 today
-- an explicit, accepted cost/latency tradeoff for reasoning quality and
genuine sector-first cascade depth, matching this session's precedent of
documenting deliberate tradeoffs (see `indianapi_poll_interval_minutes`,
`thenewsapi_poll_interval_minutes` in `app/config.py`).

### 4. Output stays wire-compatible

All 7 stages compose into the same `AnalysisOutput` shape
(`category`, `event_type`, `companies: list[CompanyMention]`) that exists
today. `app/pipeline.py`'s `_persist_alert`, `resolve_companies`, the
frontend Impact Tree, `InsightCard` -- none of them change. Sector-stage
outputs (stages 2/4/6) are ephemeral -- not persisted as new DB rows --
but each sector's one-line mechanism gets folded into the company-level
`rationale`/`key_points` text the corresponding company stage (3/5/7)
produces, so the final user-facing explanation genuinely traces sector
cause -> company effect, rather than being invented per-company in
isolation.

### 5. Failure handling

Stage 1 or 2 failing (no facts, or no sectors at all) fails the whole
article -- identical to today's existing behavior (`process_new_articles`
already retries the whole `analyze_article` call once, then marks
`ANALYSIS_FAILED`). A failure at stage 3 or later **truncates** the
pipeline at that point: whatever stages completed successfully before the
failure still get persisted (e.g. stage 5 fails -> stages 1-4's direct
companies and hop-1 sector list are known, but no hop-1 companies and no
hop-2 stages run -- direct-company results from stage 3 are still
persisted). This is a new, deliberate exception to the "single call either
fully succeeds or the article is ANALYSIS_FAILED" pattern that existed
when analysis was one call -- justified because a flaky single cascade
call should not discard already-good direct-company analysis.

## Explicitly out of scope

Adaptive/uncapped cascade depth ("keep going until the model decides to
stop") -- rejected in favor of the fixed 7-stage shape for predictable
cost. Sub-sector taxonomies for the 8 new sectors -- deferred, matches how
`other` already has none. Persisting sector-stage output as its own DB
table/model -- not needed, sector reasoning is ephemeral scaffolding for
the company stages. Any change to the frontend Impact Tree chart's
`parent_company_id`-ignoring bucketing -- a separate, already-documented
gap, unaffected by this sub-project (this sub-project makes the
underlying `AlertCompany` rows more accurate; the frontend gap is a
pre-existing, separate follow-up). Sub-project 4 (regional company
data / company profiles) -- its own future design cycle.

## Testing

`app/analysis/cascade.py`: unit tests per stage with a fake client
(mocking `.chat.completions.create` per the codebase's existing
convention), covering: each stage's happy path producing the expected
structured output, stage 1/2 failure -> whole-pipeline failure (matches
today's `ANALYSIS_FAILED` path), stage 3+ failure -> truncated-but-partial
result persisted. An end-to-end test asserting the final composed
`AnalysisOutput` has the right `impact_level`/`parent_ticker` values
across a full 7-stage run with a scripted fake client returning
per-stage canned responses. Sector taxonomy: a test that every new sector
has a valid `_other` fallback and appears in `SECTORS`. Backfill script:
`backfill_subsectors.py` (the precedent this reuses) has no test file of
its own -- it's an untested one-off, run manually. `backfill_sectors.py`
follows the same convention (untested one-off script), but the
`classify_batch`-equivalent function it calls into (if factored out as a
reusable helper rather than copy-pasted inline) should get unit test
coverage the same way any other library function in this codebase would.
