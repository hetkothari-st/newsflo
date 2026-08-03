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
amount of prompt wording corrects it. It is also why 61% of alerts come back
empty: with nothing to select from, the model returns nothing rather than
something wrong.

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

### 7. Confidence is computed, never gates anything, and has almost no range

Eternal scored 37/100 and shipped. No threshold exists anywhere.

Gating on it barely helps, though. Median `confidence_score` is 50 across
every impact level (`direct` n=846, `indirect_l1` n=25, `indirect_l2` n=10),
because two of the six signals — historical calibration (weight 0.30) and
rulebook match (0.20) — contribute 0.0 for nearly every row. Half the weight
is inert, so scores cluster tightly around 50 and the number shown to users
carries little information.

The score also measures the wrong thing for this bug: citation density,
source credibility, and freshness, but never whether the company belongs to
the story. Restoring the score's dynamic range is a real problem but a
separate one, and is out of scope here.

### 8. Text/direction incoherence

`app/pipeline.py::_persist_alert` overwrites `AlertCompany.direction` from the
measured market move, but leaves `rationale` untouched — producing a bullish
badge above bearish prose for the same company.

Contributing but lower-impact: `filtering/relevance.py::classify_relevance`
fails open (`except: return True`), and its prompt admits any "nameable
mechanism, even indirect."

### Adjacent problems found while diagnosing

Not causes of the Eternal bug, but confirmed live and worth recording.

**61% of alerts show zero companies.** 376 of 607 alerts have no
`alert_companies` row at all. The recall problem is larger than the precision
problem. Section 2's grounding addresses both: a model given a real candidate
list names companies where it currently returns nothing.

**Tier 1 of the card-back sectioning has never fired.** `alert_ripple_layers`
contains zero rows across all 607 alerts, so `generate_ripple_layers` has
never persisted a result. The locked three-tier sectioning (LLM-adaptive →
archetype template → per-sector split) is running on tiers 2 and 3 only, and
the story-adaptive sections are silently absent from every card.

Narrowed: `refine_alert`'s other three outputs *did* populate on the same
alerts — 12 summaries, 13 `TimelineEffect` rows, 14 company `why` values
(low counts because the feature shipped late; most alerts predate it). The
client and call path therefore work, and the failure is inside
`generate_ripple_layers` specifically — its nested tool schema, its
`max_tokens=1536` budget, or its validation gauntlet (`relationship` enum,
`validate_or_none` on title and note, ticker membership). Exact cause requires
a live run.

**Demo/seed data is live in the `companies` table.** `SOMETEXTILE.NS`
("Demo Textiles Ltd") is resolvable and was injected into real alerts by the
sector fan-out.

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

   This is not sufficient on its own. `ripple_layers.py:180-200` lets
   LLM-generated layers (tier 1) claim tickers *before* bucket assignment
   runs, and `refinement.py:553` offers every company — fan-out included — to
   `generate_ripple_layers`. A generated section can therefore sort a fan-out
   company into a story-specific section and bypass this routing entirely.
   Fix both ends: offer only `direct_mention` rows to `generate_ripple_layers`,
   and exclude `sector_inference` rows from generated-layer claiming so they
   always fall through to `SECTOR_WIDE`.
2. Sector-inference rows persist `rationale = None` rather than the template
   string. `is_exposure_only` already renders such rows without a number or
   score.
3. Confidence floor at 40 — minor cleanup only, explicitly **not** a defense
   against the bug. Measured against production data, a floor of 40 removes
   20 rows of 881: 3 of 846 `direct`, and only 16 of 557 `sector_inference`
   (2%) — 2% of exactly the category that produced Eternal.

   The reason is structural. Median `confidence_score` is 50 at every impact
   level, because `calibration` contributes 0.0 for nearly every row (fewer
   than `CALIBRATION_SAMPLE_THRESHOLD`=5 outcome samples per company exist
   yet) and `rulebook match` is usually 0 as well — half the total weight is
   dead, so scores cluster. Raising the floor to 50 does not help: it starts
   cutting correct `direct_mention` rows at the median while still keeping
   half the fan-out.

   More fundamentally, none of the six `compute_confidence` signals asks
   whether a company belongs to the story. They measure citation density,
   source, and freshness. Eternal scored 37 for lacking a rulebook match and
   calibration history, not for being a food-delivery company on a crude-oil
   story. A well-cited, entirely irrelevant company scores 50 like a correct
   one.

   Relevance filtering is therefore carried by Section 1's re-bucketing
   (structural), Section 2 (grounding), and Section 3 (an explicit
   per-company belongs/does-not-belong judgment). The floor is retained only
   to trim the genuinely degenerate tail.

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

### Section 8 — Tier-1 ripple-layer repair

The story-adaptive sections are the top tier of the locked three-tier card-back
sectioning and have never produced a row. Restoring them matters here and not
only cosmetically: tier 1 claims tickers before bucket assignment, so it is
also the layer that must be taught to leave `sector_inference` rows alone
(see Section 1).

1. Reproduce live against a known alert with several companies, logging the
   raw provider response before validation.
2. Identify which of the three candidate causes fires — empty/degenerate tool
   response (the `max_tokens` failure mode documented in `cascade.py`'s
   `_identify_cascade_companies_per_sector`), a rejected `relationship` enum,
   or `validate_or_none` rejecting titles/notes.
3. Fix, and add a regression test asserting a populated
   `alert_ripple_layers` for a representative alert.

The current silent degradation to `[]` is itself part of the problem: a total
tier-1 failure is indistinguishable from "no sections applied." Add a log line
so this cannot recur unnoticed.

### Section 9 — Purge demo data from `companies`

`SOMETEXTILE.NS` ("Demo Textiles Ltd") is a live, resolvable row and was
injected into real alerts by the sector fan-out. Remove it and audit for other
seed rows from `seed_feed_v2_demo.py` / `seed_car_review_demo.py`. Add a guard
so demo seeds cannot resolve into production alerts.

### Section 10 — Migration

- SQL/Python migration across all 607 alerts: re-bucket `sector_inference`
  rows, strip template rationales, drop sub-floor rows. Minutes, zero API
  calls.
- Full reanalysis of the most recent 7 days through the new pipeline, via the
  existing `reanalyze_cascade.py`. 7 days covers what users actually scroll
  while staying inside free-tier quota; the window is a script argument, so a
  wider pass is a re-run, not a code change.

## Success criteria

Measured on the Section 0 harness, before and after:

1. **Zero** must-exclude companies (Eternal-class false positives) on the
   golden set.
2. Alerts with zero companies falls well below the current 61%. Section 2's
   grounding is the lever; the exact target is set once the harness gives a
   baseline.
3. No `sector_inference` row renders in a DIRECT-family bucket.
4. `alert_ripple_layers` is populated for alerts that warrant sections.

## Build order

`0 → 1 → 2 → 3 → 10` delivers the majority of the improvement.
`4 → 5 → 6 → 7 → 8 → 9` follow.

Section 5 is slow but is the one that prevents the whole class of bug; it may
be pulled earlier if the Section 0 harness shows taxonomy driving residual
false positives. Section 9 is a few minutes' work and can be done at any
point.

## Known consequences

Measured against production data, the narrowing does not thin the typical
alert — it deflates a bloated minority.

```
companies per alert now:   median 1   mean 3.8   p90 10   max 35
alerts with zero fan-out:  182 of 231 non-empty alerts
projected after Section 4: median 1   mean 2.8   p90  6   max 21
```

Fan-out is concentrated, not spread: 182 of the 231 non-empty alerts have none
at all, so the median alert is unchanged and the reduction lands on exactly
the alerts carrying the errors.

Worked example — alert 9020 (29 companies today):

- **Remain DIRECT (analyzed):** HPCL, BPCL, IndiGo, Asian Paints, HUL — each
  defensible on a crude shock (jet fuel, crude-derived paint inputs,
  packaging).
- **Move to SECTOR_WIDE:** Coal India, ONGC, Reliance, GAIL, ITC, Nestlé —
  genuine sector exposure, now labelled as exposure rather than analysis.
- **Dropped:** Eternal (sub-sector targeting selects `staples_food`, not
  `personal_care`), plus the whole L1/L2 fan-out — Bajaj Auto, Maruti, Eicher,
  M&M, Tata Motors, HDFC Bank, Axis, Bajaj Finance, NTPC, PowerGrid,
  UltraTech.

29 → roughly 12, each defensible.

The `SECTOR_WIDE` band will still visibly thin on some alerts. That is the
accepted trade of the chosen output shape, and it will be felt before
Section 2 lands and begins adding *correct* companies back.

## Category and layout preservation

No category is added, removed, or renamed. Explicitly preserved:

- The three-tier card-back sectioning: LLM-adaptive generated layers →
  static archetype template → per-sector split. All three tiers retained.
- All seven `_LAYER_ORDER` relationships, in existing order.
- The multi-sector DIRECT split into per-sector sections.
- `impact_level` values `direct` / `indirect_l1` / `indirect_l2`.

The only display change is which existing bucket a fan-out row lands in:
`SECTOR_WIDE` rather than `DIRECT`.

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
- Restoring dynamic range to `confidence_score` (see root cause 7). Real, but
  a separate problem from the hallucination bug this design addresses.

## Status at merge

Measured on the Section 0 evaluation harness:

1. **Zero must-exclude companies on the golden set:** VERIFIED, but on one
   labelled case. `score_golden.py` reports alert 9020 at precision 1.00,
   recall 1.00, 0 forbidden. `tests/golden/cases.py` holds one case; ~29 more
   remain to be labelled by a human.

2. **Alerts with zero companies well below 61%:** NOT MET. Live database is
   377/607 = 62.1%, essentially unmoved. The migration structurally cannot
   change this — only a grounded reanalysis can, and that is blocked on
   exhausted provider quota.

3. **No sector_inference row in a DIRECT-family bucket:** VERIFIED at code
   level across all three claiming tiers, with tests.

4. **alert_ripple_layers populated:** NOT MET. Still zero rows. Root cause
   unconfirmed because reproduction requires a live LLM call and quota is
   exhausted; two plausible fixes plus exhaustive diagnostic logging shipped,
   so the next real run will name the cause rather than degrade silently.

## Known limitations at merge

- `business_desc` is populated for only 12 of 1016 companies, so the candidate
  grounding currently ships as ticker + name + sub-sector, with the
  description field largely absent. `backfill_business_profiles.py` is
  resumable and ready to run.

- Moving the confidence floor to compare against the pre-multiplier score
  materially widens persistence: `indirect_l1` rows scoring 40–56 and
  `indirect_l2` rows scoring 40–87 now persist where previously they never
  could. On a change themed around reducing company counts, expect counts to
  rise somewhat on the first production run.

- `reanalyze_cascade.py` now correctly deletes `CalibrationSample` and
  `CarOutcome` rows alongside the `AlertCompany` rows it replaces. That is
  correct — they are meaningless without their parent — but it means a
  reanalysis irrecoverably discards outcome and calibration history for the
  alerts it touches. Anyone running it over a date range should know that.

- `reanalyze_cascade.py` does not apply `CONFIDENCE_FLOOR`, unlike the live
  pipeline. Pre-existing divergence between the one-off script and
  `_persist_alert`, not introduced by this work.
