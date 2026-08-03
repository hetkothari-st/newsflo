# Impact Analysis Precision — Design

**Date:** 2026-08-03
**Status:** Approved, not yet implemented

## Problem

The app's core selling point is the affected-companies list on an alert: which
companies a news story touches, why, and how directly. That list currently
contains companies with no genuine connection to the story, presented as if
they had been analyzed.

Confirmed case — alert 9020, article *"Crude oil supply shock hits refiners"*:

```
company  = Eternal Ltd. (ETERNAL.NS)   -- food delivery / quick commerce
basis    = sector_inference
impact_level = direct
confidence_score = 37
rationale = "Sector-wide exposure via fmcg: Higher crude inflates packaging
             materials and logistics costs..."
```

No LLM ever reasoned about Eternal for this article. Code placed it there, and
the card back rendered it as **directly affected**.

A single alert like this is enough to destroy trust in the product.

## Root cause

Eight distinct causes, ranked by contribution.

### 1. Deterministic sector fan-out (largest single source)

`app/analysis/cascade.py::_sector_fanout_mentions` emits one synthetic
"sector-wide" `CompanyMention` per sector, at every cascade level.
`app/companies/resolution.py::resolve_companies` expands each into the top
`TOP_N_SECTOR_COMPANIES` (5) companies of that sector, ranked by `_TIER_RANK`
(NIFTY50 first).

Eternal is NIFTY50 and is tagged `sector='fmcg'`, so it is the top-ranked
constituent of a 123-company bucket. Any article whose cascade touches `fmcg`
at any level auto-injects it, with a template rationale that reads like
analysis.

Production data:

| basis | rows |
|---|---|
| `direct_mention` | 324 |
| `sector_inference` | 557 |

**63% of every company shown across 607 alerts is algorithmic fan-out with no
article-specific reasoning.** Max companies on a single alert: 35.

### 2. Fan-out rows are displayed as directly affected

`app/market/ripple_layers.py:127` assigns the card-back bucket from
`impact_level`:

```python
if alert_company.impact_level == "direct":
    relationship = "DIRECT"
```

`_sector_fanout_mentions` stamps primary-sector fan-out as
`impact_level="direct"`, so fan-out rows land in the DIRECT bucket, visually
identical to genuinely analyzed companies. The existing `SECTOR_WIDE` bucket
(`_LAYER_ORDER`, label `"sector-wide spillover"`) is effectively unreachable
for them.

### 3. Company taxonomy is too coarse and partly wrong

12 sectors for 1017 companies. `other` = 180 rows (18%). The `fmcg` bucket
(123) contains Asian Paints (paints/chemicals), Eternal (food delivery),
Hindustan Unilever, and Nestlé together — so a crude-oil fan-out pulls Asian
Paints and Eternal off the same label.

`sub_sector` is populated for 828 rows and is meaningfully finer.
`market_cap` is populated for only 43, so `cap_tier` is mostly null.

### 4. No grounding at company-selection time

The model names companies from parametric memory. It is never given a
candidate list to select from. `business_desc` exists on the `companies` table
but is populated for only **13 of 1017** rows, and is never used during
analysis.

Retrieval-free entity extraction is the standard hallucination setup; no
amount of prompt wording corrects it.

### 5. No verification pass over the company list

`_generate_edges` verifies *rulebook edges*. Nothing re-reads the assembled
company list and asks whether each company belongs.

### 6. All stages actually run on one cheap model

`app/analysis/claude_client.py::_GeminiCompletions.create` accepts
`**_ignored`, silently discarding the `model` kwarg. Whenever `GEMINI_API_KEY`
is set, the `MODEL` (`llama-3.3-70b-versatile`) vs `FALLBACK_MODEL`
(`openai/gpt-oss-20b`) distinction threaded through `cascade.py` is dead code —
every stage runs on `gemini-flash-latest`.

`temperature` is never set on any call, so Gemini defaults to 1.0 on what is
fundamentally an extraction task.

### 7. Confidence is computed but never gates anything

Eternal scored 37/100 and shipped. No threshold anywhere.

### 8. Text/direction incoherence

`app/pipeline.py::_persist_alert` overwrites `AlertCompany.direction` from the
measured market move, but leaves `rationale` untouched — producing a bullish
badge above bearish prose for the same company.

Contributing but lower-impact: `filtering/relevance.py::classify_relevance`
fails open (`except: return True`), and its prompt admits any "nameable
mechanism, even indirect."

## Decisions

Three decisions were made before this design, and they constrain everything
below.

**Output shape — precision core plus an honest second tier.** Verified,
article-specific companies form the core. Sector-exposure companies are kept
but quarantined: clearly separated, no fabricated per-company rationale, no
confidence badge.

**No layout or category changes.** The second tier reuses the existing
`SECTOR_WIDE` bucket, existing labels, existing ordering. No new section type,
no new division category, no frontend redesign.

**Free APIs now, paid later.** The app is mid-development on free Gemini/Groq
tiers. Six of the eight root causes are architectural and are fixed without
spending anything; the paid migration later becomes a model-tier swap on an
already-clean pipeline rather than a patch over a leaky one.

**Migration scope — migrate all, reanalyze recent.** A zero-API SQL migration
across all 607 alerts, followed by a full reanalysis of only the most recent
7 days.

## Design

### Section 0 — Evaluation harness

Build first. Nothing below is measurable without it.

A golden set of ~30 alerts drawn from the existing 607, hand-labelled with
expected companies (must-include and must-exclude). Eternal-on-crude-oil is
fixture #1. A script runs the pipeline over the set and reports precision,
recall, and the named false positives.

This is what converts "feels better" into "false positives fell from 41% to
4%", and it is what allows tuning on free APIs and then proving the paid
model swap actually helped.

### Section 1 — Stop the bleed

No API calls. Immediate.

1. `ripple_layers.py:127` — dispatch the bucket on `basis`, not
   `impact_level`. `sector_inference` routes to `SECTOR_WIDE`.
2. Sector-inference rows persist `rationale = None` rather than the template
   string. `is_exposure_only` already renders such rows without a number or
   score.
3. Confidence floor: drop rows below a threshold at persist time. Starting
   value 40 (Eternal scored 37; a plain `direct_mention` row scores 50), tuned
   against the Section 0 harness. Note the interaction with
   `LEVEL_CONFIDENCE_MULTIPLIER` — an `indirect_l2` row is multiplied by 0.45,
   so a floor of 40 removes essentially all of them. Given that the L2 rows
   are already almost entirely fan-out padding, that is the intended effect,
   not a side effect to design around.

After this, alert 9020 is no longer misleading. It is not yet correct — that
is Sections 2-4.

### Section 2 — Grounding

The single largest hallucination reduction, and it costs nothing recurring.

1. Backfill `business_desc` across all 1017 companies via the existing
   `backfill_business_profiles.py`. One-time batched job. The 13 existing rows
   confirm the right shape ("Refines crude oil and runs retail fuel,
   petrochemical, and telecom businesses.").
2. At company-identification time, query candidates for the named
   sectors/sub-sectors and include them in the prompt with their descriptions.
   The model selects from a real list instead of recalling from memory.
3. Enum-constrain `ticker` to that candidate list — the same pattern already
   used for `parent_ticker` (`build_company_tool`) and `llm_only_edges`
   (`build_edge_verify_tool`). Keep a defensive post-filter: `cascade.py:282`
   documents that provider-side enum enforcement is not reliable for nested
   array items.

Consequence: `_find_direct_company`'s fuzzy substring matching becomes
near-dead code, since tickers arrive pre-validated against real rows.

### Section 3 — Verification pass

One batched call per alert after the company list is assembled. For each
company: does a specific mechanism from *these* facts reach *this* company's
business? Keep or drop, with a stated reason. Tickers enum-constrained to the
assembled list, so the pass can only judge — never add.

Cost-neutral: removing fan-out's downstream work frees more calls than this
consumes.

### Section 4 — Fan-out repair

Constrained, not deleted — the second tier is intentional.

- Primary sectors only; no fan-out at `indirect_l1` / `indirect_l2`.
- Only when the sector's own mechanism is genuinely broad. Sector-wide
  spillover is real for a rate or commodity move; it is not real for one
  company's earnings miss.
- Select by `sub_sector`, not `sector`. Crude oil reaching `fmcg` should pull
  `staples_food`, not `personal_care` or `paints`.
- `TOP_N_SECTOR_COMPANIES`: 5 → 3.

### Section 5 — Taxonomy repair

Reclassify the 180 `other` rows and split the overloaded buckets, driven by
the Section 2 `business_desc` backfill. Eternal moves out of
`fmcg/personal_care`.

This is what prevents the *next* Eternal, in a sector not yet inspected.

### Section 6 — Model routing

- `GeminiAdapter` honors the `model` kwarg (or an explicit tier argument), so
  the existing per-stage model selection stops being dead code.
- Set a low `temperature` on extraction stages.

Remains free today. The paid migration then points hard stages at a stronger
model with no other change.

### Section 7 — Coherence

When `_persist_alert` overwrites `direction` from the measured move, the stale
`rationale` must be suppressed or regenerated rather than left contradicting
the badge.

### Section 8 — Migration

- SQL/Python migration across all 607 alerts: re-bucket `sector_inference`
  rows, strip template rationales, drop sub-floor rows. Minutes, zero API
  calls.
- Full reanalysis of the most recent 7 days through the new pipeline, via the
  existing `reanalyze_cascade.py`. 7 days covers what users actually scroll
  while staying inside free-tier quota; the window is a script argument, so a
  wider pass is a re-run, not a code change.

## Build order

`0 → 1 → 2 → 3 → 8` delivers the majority of the improvement.
`4 → 5 → 6 → 7` follow.

Section 5 is slow but is the one that prevents the whole class of bug; it may
be pulled earlier if the Section 0 harness shows taxonomy driving residual
false positives.

## Known consequences

Section 1's confidence floor and Section 4's narrowing will visibly thin some
alerts, including within the `SECTOR_WIDE` band. This is the accepted trade of
the chosen output shape. The thinning will be felt before Section 2 lands and
begins adding *correct* companies back.

`indirect_l1` (25 rows) and `indirect_l2` (10 rows) across 607 alerts are
already almost entirely fan-out padding rather than real ripple reasoning.
Once fan-out is constrained, whether the L1/L2 cascade stages earn their call
cost at all becomes an open question — to be answered with Section 0 data, not
assumed here.

## Out of scope

- Any frontend layout, section, or category change.
- Full reanalysis of all 607 alerts (deferred to the paid-API migration, where
  it is a cheap batch job).
- Replacing the rulebook/playbook system.
