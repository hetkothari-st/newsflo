# Reasoning Panel Evidence UI — Design

## Goal

Surface the reasoning-engine fields added to the backend
(`docs/superpowers/specs/2026-07-15-reasoning-engine-upgrade-design.md`,
`docs/superpowers/plans/2026-07-15-reasoning-engine-upgrade.md`) in the
frontend: `confidence_band`, `reasons`, `evidence_refs`, `risks`,
`assumptions`, `unknowns`, `alternative_hypothesis`,
`confidence_contributors`, `confidence_penalties` (per company), and
`event_type` (per alert). These fields already exist in every `GET
/api/alerts`/`GET /api/alerts/{id}` response (`backend/app/routers/alerts.py`)
and the websocket broadcast, but nothing in the UI shows them yet.

Scope: `ReasoningPanel` only (`frontend/src/components/ReasoningPanel.tsx`).
Because `ConfidenceTree` (`frontend/src/features/visualize/charts/
ConfidenceTree.tsx:28`) already renders `ReasoningPanel` for the selected
company, this single change also reaches the charts page automatically.
`CompanyPage.tsx`'s separate "Latest Signal" section (a different component,
backed by a different `LatestAlertSignal` type) is explicitly out of scope —
a follow-up if wanted later.

## Current state (grounded in the actual code)

`ReasoningPanel` (`frontend/src/components/ReasoningPanel.tsx:10-50`) today
renders, top to bottom: a header line (`{name} · {ticker}`), a bullet list of
`key_points` (falling back to `splitRationaleIntoPoints(rationale)` for
legacy alerts with no `key_points`), one muted `precedentLine(...)` caption,
an optional past-mentions section, and an optional "view details" link. It's
rendered by `CompanyChip.tsx:40` when a chip is expanded (progressive
disclosure — the chip itself is collapsed by default in a list).

`frontend/src/lib/api.ts:22-52` defines `AlertCompany`/`Alert` as the single
source of truth every component imports; `WsAlertCompany`/`WsAlert`
(lines 57-58) derive via `Omit`, so new fields added to the base interfaces
propagate to the websocket path with no separate edit.

`frontend/src/features/visualize/colors.ts` has two existing, dataviz-skill-
validated palettes: `SECTOR_COLOR` (categorical) and `CONFIDENCE_RAMP` (a
5-step sequential blue ramp for numeric `confidence_score` 0-100, lines
51-62). No generic Chip/Badge component exists — pills are bespoke per use
(`SentimentPill.tsx`, `CategorySwatch.tsx`).

## Design

### 1. Types (`frontend/src/lib/api.ts`)

Extend `AlertCompany` with the new per-company fields, all typed to match
what legacy alerts (rows persisted before this feature) actually return —
`null`/`[]`, never `undefined`, per the backend's `_decode_json_list`/column
defaults:

```ts
export interface AlertCompany {
  // ...existing fields unchanged...
  confidence_band: string | null; // LOW | MODERATE | HIGH | VERY_HIGH | null (legacy)
  reasons: string[];
  evidence_refs: string[];
  risks: string[];
  assumptions: string[];
  unknowns: string[];
  alternative_hypothesis: string | null;
  confidence_contributors: string[];
  confidence_penalties: string[];
}

export interface Alert {
  // ...existing fields unchanged...
  event_type: string | null; // legacy alerts have null
}
```

No other type changes needed — `WsAlertCompany`/`WsAlert` inherit
automatically.

### 2. Confidence band badge — reuses the existing validated ramp, no new colors

`confidenceColor(score: number)` already maps 0-100 to 5 validated hex steps.
Rather than validating a second palette for the 4-value band enum (real
work, per the dataviz skill's process), map each band to one representative
point on the *same* already-validated ramp:

```ts
// frontend/src/features/visualize/colors.ts — add:
const BAND_REPRESENTATIVE_SCORE: Record<string, number> = {
  LOW: 10,
  MODERATE: 50,
  HIGH: 75,
  VERY_HIGH: 95,
};

export function confidenceBandColor(band: string): string {
  const score = BAND_REPRESENTATIVE_SCORE[band] ?? BAND_REPRESENTATIVE_SCORE.MODERATE;
  return confidenceColor(score);
}
```

New component `frontend/src/components/ConfidenceBandPill.tsx`, styled like
`SentimentPill` (`rounded-full border-[1.5px]`), colored via
`confidenceBandColor`, rendering the band's translated label. Not rendered at
all when `confidence_band` is `null` (legacy alert) — no placeholder pill.

### 3. `ReasoningPanel` changes

- Header line gains the badge from #2, shown only when `company.confidence_band`
  is non-null: `{name} · {ticker}` stays as-is, badge renders to its right.
- Below the existing `key_points` list and `precedentLine`, a new collapsible
  block, rendered only when `company.reasons.length > 0` (so legacy alerts
  with no new fields render identically to today — zero layout shift):
  - A toggle button, closed by default, label `t('reasoning.whyThisCall')`
    (e.g. "Why this call") with a chevron, same interaction pattern as
    `CompanyChip`'s own expand (local `useState`).
  - When open, in order:
    1. **Reasoning** — `reasons` as a bullet list (same bullet style as
       `key_points`).
    2. **Evidence** — `evidence_refs`, cleaned for display: an entry starting
       with `RULE_` renders as a small muted tag (e.g. "Rule: repo rate
       cut" — human-readable via a small id→label lookup, falling back to the
       raw id if unrecognized); an entry prefixed `article:` or `historical:`
       strips the prefix and renders as plain text with a small superscript
       label ("Article" / "Historical").
    3. **Alternative view** — `alternative_hypothesis`, rendered only if
       non-null, as one italicized muted line.
    4. **Risks & unknowns** — `risks`, `assumptions`, `unknowns` concatenated
       into one small muted bullet list under a single sub-heading (not three
       separate sections — individually each list is usually 0-3 short
       items, too granular to warrant three headings in a feed UI).
    5. **Confidence breakdown** — only rendered if `confidence_contributors`
       or `confidence_penalties` is non-empty: `confidence_contributors` as a
       short "+" list (`text-bullish` or similar positive tone),
       `confidence_penalties` as a short "−" list (`text-bearish`/muted-amber
       tone). This is what makes the badge from #2 inspectable, not just
       decorative — directly serves the "expose uncertainty" product
       principle.
    6. If `alert.event_type` is non-null, one small muted line at the bottom
       of this block: `t('reasoning.eventType', { type: eventTypeLabel })`.
       `ReasoningPanel` currently takes only `company: AlertCompany` as a
       prop — it needs a second, optional `eventType?: string | null` prop
       from the caller (`CompanyChip`/`ConfidenceTree` both have `alert` in
       scope already to pass it through).

### 4. Rule-id → label lookup for evidence display

A small new file, `frontend/src/lib/ruleLabels.ts`, mapping the 9 rule IDs
from `backend/app/reasoning/rulebook.py` to short human labels (kept in sync
manually — same "duplicated on purpose, not imported" tradeoff the backend
itself uses between `confidence.py` and `blender.py` for
`CALIBRATION_SAMPLE_THRESHOLD`, since frontend can't import backend Python):

```ts
export const RULE_LABELS: Record<string, string> = {
  RULE_REPO_RATE_CUT: 'Repo rate cut',
  RULE_REPO_RATE_HIKE: 'Repo rate hike',
  RULE_INFLATION_RISE: 'Inflation rise',
  RULE_CRUDE_OIL_UP: 'Crude oil up',
  RULE_CURRENCY_INR_WEAKENS: 'INR weakens',
  RULE_GOVERNMENT_CAPEX: 'Government capex',
  RULE_EARNINGS: 'Earnings',
  RULE_MERGER_ACQUISITION: 'Merger/acquisition',
  RULE_BANKING_METRICS: 'Banking metrics',
};

export function ruleLabel(ref: string): string {
  return RULE_LABELS[ref] ?? ref;
}
```

Similarly, `event_type` values (`backend/app/analysis/schemas.py::EVENT_TYPES`)
get a small label map in the same file for the #3.6 display line.

### 5. i18n

New keys in `frontend/src/lib/i18n.ts`'s translation table, following the
existing `reasoning.*` key pattern (`reasoning.previously`,
`reasoning.viewDetails`, etc.), each with all languages the file already
supports (matching whatever set `reasoning.previously` currently has — no
new languages, no English-only fallback gaps):
`reasoning.whyThisCall`, `reasoning.reasoning`, `reasoning.evidence`,
`reasoning.alternativeView`, `reasoning.risksAndUnknowns`,
`reasoning.confidenceBreakdown`, `reasoning.eventType`, plus the four band
labels (`reasoning.confidenceLow` / `Moderate` / `High` / `VeryHigh`).

## Explicitly deferred

- `CompanyPage.tsx`'s "Latest Signal" section (separate component/type,
  follow-up if wanted).
- A dedicated evidence-graph/visual explorer — the design bible's brainstormed
  docs mention this as a "future enhancement," not needed for v1.
- Any new color palette — reusing the existing validated ramp avoids this
  entirely.

## Testing

Component tests following the existing pattern (this repo tests nearly every
component — e.g. `LivePriceReadout.test.tsx`, `CompanyPage.test.tsx`):
`ConfidenceBandPill` renders the right label/color per band and renders
nothing for `null`; `ReasoningPanel` renders identically to today when
`reasons` is empty (legacy-alert regression guard — the single most
important test in this spec, since it's the thing that must never visually
break for old data); `ReasoningPanel` shows the new block when `reasons` is
non-empty and correctly separates contributors (+) from penalties (−);
`ruleLabel`/event-type label lookups fall back to the raw string for an
unrecognized id.
