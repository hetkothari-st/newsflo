# Tree-Structured Graphs v4 — Design

## Goal

Redesign Sector and Positive/Negative Split into real hierarchical trees matching
the structure of the user's reference mockups (`docs/graph-type-references/`),
executed with proper visual/interaction quality this time — not the SVG node-link
diagram that failed twice before. Add two new tree types (Confidence, Timeline)
that need two new data fields. Remove the current 5-company-per-alert cap. Add a
Normal/Drilldown breadth toggle shared across every chart on the page.

Deferred to a separate future design (per explicit user decision): Impact Tree and
all relationship-graph types (Ripple Effect, Supply Chain, Multi-Level Impact Tree
levels 2-5, Economic Chain, Knowledge Graph) — these need the LLM to assert
company↔company/commodity relationships that don't exist in the data today, a real
fabrication-risk surface that deserves its own careful anti-fabrication design.

## Why the SVG approach failed twice, and why HTML/CSS trees fix it

`CompanyTree.tsx` (deleted in the v3 redesign) was a hand-rolled SVG node-link
diagram: canvas-measured text, computed `<path>` connectors, manual truncation.
Both user complaints ("bad, non-aesthetic," "cant even read the names") trace to
that implementation, not to trees as a form — organic SVG connectors read as
generic/AI-flowchart-ish, and canvas text measurement is fragile (it's exactly what
produced the truncated "NIFTY NEXT ..." bug fixed in that era).

This round's trees are **plain nested HTML with CSS-drawn guide lines** — the same
technique as a VS Code file explorer or a filesystem tree: a `<ul>`/`<li>`
hierarchy, each level indented via `padding-left`, connector lines via
`border-left` on the list container plus a small `border-bottom` "elbow" per item
(a well-known, easy-to-get-right pattern; no SVG, no canvas, no manual line-drawing
math). Text truncates/wraps with plain CSS (`truncate`, `line-clamp`), matching
every other list-heavy component already in this codebase (`CompanyChip`,
`ReasoningPanel`'s past-mentions list). This removes the entire bug class that sank
the last two attempts, not just changes the color palette.

## Data model changes

### New backend fields

Two new fields on `CompanyMention` (`backend/app/analysis/schemas.py`),
`RECORD_ANALYSIS_TOOL` (`backend/app/analysis/claude_client.py`), `AlertCompany`
(`backend/app/models.py`), and the API response (`backend/app/routers/alerts.py`'s
`_serialize_alert`, `frontend/src/lib/api.ts`'s `AlertCompany` interface):

- **`confidence_score`**: `int`, 0-100. A new field, distinct from the existing
  `confidence` column (which is `"llm_estimate" | "calibrated"` — a data-quality
  flag about whether historical calibration exists, not a per-call confidence
  score). Naming it `confidence_score` avoids colliding with that existing field's
  meaning. Required in the tool schema, just like `magnitude_low`/`magnitude_high`
  are today.
- **`time_horizon`**: `str` enum, one of `Immediate | Short-Term | Medium-Term |
  Long-Term` — matching the master spec's own `ImpactNode.timeHorizon` vocabulary
  (not the mockup's 5 literal buckets like "1 Week"/"Quarter" — those are harder
  for a model to classify reliably than 4 broad, well-separated buckets, and the
  master spec already settled on 4). Required in the tool schema.

Both get a real prompt rule (new rules 9-10, following the existing 8) explaining
what they mean and how to set them, same rigor as the existing rules — e.g.
`confidence_score` should reflect how directly-evidenced the call is (a named
company with a clear stated mechanism scores higher than a sector-level inference),
`time_horizon` should reflect when the mechanism plays out (a tariff taking effect
immediately vs. an earnings-cycle effect vs. a multi-quarter structural shift).

### `effect_type` — no new field needed

The user's `effect_type: "Direct"` example maps directly onto the existing `basis`
column (`direct_mention | sector_inference`) — display it in the UI as "Direct" /
"Sector-inferred" rather than adding a duplicate field.

### `impact_level` — no new field needed

Derived client-side via the existing `rankByMagnitude` ordinal-ranking approach
(same reasoning as the shipped Impact chart: magnitude values have no fixed global
scale, so an LLM-asserted 1-5 tier would be arbitrary in a way a relative rank
isn't). A new `transforms.ts` helper buckets `rankByMagnitude`'s output position
into 5 tiers per side (bullish/bearish) for anywhere a 1-5 badge is wanted.

### Removing the 5-company cap

`ANALYSIS_INSTRUCTIONS` rule 5 (`claude_client.py`) currently reads: *"List at
most 5 companies total, fewer if you are not genuinely confident in more."*
Replace with guidance that drops the numeric cap but keeps the quality bar: list
every company with a genuine, specific, defensible link — do not pad the list to
hit a target count, and do not omit a real one to stay under an old cap. Rule 1's
secondary "3-5 specific companies" phrasing gets the same edit. The JSON tool
schema already has no `maxItems` on the `companies` array (confirmed — the cap was
prompt-only), so no schema change is needed there, only the prompt text.

This is a real behavior change to a production LLM pipeline, not a mechanical
edit — it needs its own verification pass: run it against a sample of recent real
articles (not just unit-test fixtures) and confirm output quality doesn't degrade
(padding, weaker rationales, cost/latency increase) before calling it done. Every
shipped chart's layout was also sized assuming ≤5 items (`ImpactBar`'s
`MAX_BAR_PX`, the `grid-cols-2 sm:grid-cols-3` treemap grid) — those assumptions
get revisited as part of the tree rebuild anyway (trees scroll, they don't need a
fixed small-N grid), but `ImpactBar`/`TierRows` (unchanged this round) need a
correctness check against a >5-company alert before shipping the uncap.

## Normal / Drilldown toggle

A single toggle, rendered once at the `AlertChartsPage` level (not per-chart),
applying uniformly to every chart on the page (Sector, Tier, Impact, Split,
Confidence, Timeline):

- **Normal** (default): only `basis === 'direct_mention'` companies — "primarily
  affected."
- **Drilldown**: every company on the alert, direct and sector-inferred — "wider
  picture."

This needs no new data (`basis` already exists) — it's a filter applied to
`alert.companies` before handing the resulting array to whichever chart component
is active, so no individual chart needs new props or internal toggle logic beyond
receiving a possibly-smaller `companies` array, exactly like they do today.

Edge case: an alert with zero `direct_mention` companies (100% sector-inferred)
shows an empty Normal view. Handle it the same way `AlertCompanies.tsx` already
handles its own empty states — a short message ("No directly-confirmed companies
for this alert — try Drilldown for the wider sector picture") rather than a blank
chart.

## The shared tree primitive

A new `Tree`/`TreeBranch`/`TreeLeaf` component set in
`frontend/src/features/visualize/charts/tree/` (or similar), used by both Sector
Tree and Split Tree (and Confidence/Timeline Tree, which are structurally the same
shape — one level of grouping, companies as leaves):

- Root: article title (small, muted, matches the existing `AlertChartsPage`
  header — the tree's root doesn't need to repeat it prominently, this differs
  from the mockups which show "News" as the root node, since our page already has
  a persistent header serving that role).
- Branch: one per group (sector / Positive-or-Negative / confidence band / time
  horizon bucket), collapsible (default expanded, tap to collapse — new
  interactivity, matches the master spec's "expand/collapse" requirement).
- Leaf: one per company — ticker, direction glyph, and whatever the tree's
  specific badge is (confidence %, time horizon label, nothing extra for
  Sector/Split beyond what's already shown). Tapping a leaf opens the existing
  `ReasoningPanel` inline below it (reusing `useCompanySelection`, unchanged).
- Connector lines: CSS `border-left` on the branch's child `<ul>`, `border-bottom`
  elbow per leaf/branch — straight lines only, no curves.
- Color: branch color reuses whatever's semantically correct for that tree
  (validated sector palette for Sector Tree; `text-bullish`/`text-bearish` for
  Split Tree; a new sequential single-hue ramp, light→dark by `confidence_score`,
  for Confidence Tree, validated the same way the sector palette was — see
  `dataviz` skill; Timeline Tree's branches are chronological, not evaluative, so
  no branch color beyond the existing per-company direction glyph).

## The four trees

### 1. Sector Tree (rebuild, replaces the current grid-of-tiles `SectorTreemap`)

Structure: one branch per sector present (using existing `groupBySector`), leaves
are that sector's companies. Matches mockup `08-sector-tree.png`'s two-level shape
exactly, styled with the tree primitive above instead of the mockup's plain
monospace text.

### 2. Positive/Negative Split Tree (rebuild, replaces the current `SplitDonut`)

Structure: two branches (Positive / Negative, using existing `groupByImpact`),
leaves are that direction's companies, each leaf ranked within its branch via
`rankByMagnitude` (strongest conviction first). Matches mockup
`06-positive-negative-split.png`.

The current `SplitDonut`'s composition read (a `2 Bullish · 0 Bearish`-style count
line) was reviewed as genuinely good work — keep a small version of it as a
one-line summary above the tree (reusing the existing count-computation logic, not
the SVG donut itself, which gets removed along with the rest of `SplitDonut.tsx`).

### 3. Confidence Tree (new)

Structure: single flat branch, all companies ranked by `confidence_score`
descending (using a new `rankByConfidence` transform, same shape as
`rankByMagnitude`), each leaf showing its `confidence_score` as a `NN%` badge
colored via the new sequential ramp. Matches mockup `05-confidence-tree.png`.

### 4. Timeline Tree (new)

Structure: one branch per `time_horizon` bucket present, in fixed order
(`Immediate → Short-Term → Medium-Term → Long-Term`), leaves are that bucket's
companies. Matches mockup `07-timeline-tree.png`'s shape (the mockup's specific
bucket labels — "1 Week," "Quarter" — are illustrative; see the data-model section
above for why this spec uses the master spec's 4-bucket vocabulary instead).

## Page integration

`AlertChartsPage.tsx`'s `CHARTS` array grows from 4 to 6 entries (`sector, tier,
impact, split, confidence, timeline`), in that order — `tier`/`impact` unchanged
this round, `sector`/`split` rebuilt, `confidence`/`timeline` new. The
Normal/Drilldown toggle sits in the page's header row, next to the existing back
button, applying to whichever chart is currently active (and persisting across
swipes between chart types, since it's page state, not per-chart state).

## Testing

- Backend: prompt/schema changes need a real-article verification pass (not just
  unit tests) confirming quality holds without the 5-company cap; unit tests for
  the two new required fields flowing through `resolve_companies` → `_persist_alert`
  → `_serialize_alert` unchanged in shape from the existing `direction`/`rationale`
  pattern.
- Frontend: the shared tree primitive gets its own test suite (branch
  expand/collapse, leaf tap → `ReasoningPanel`, empty branch handling) once,
  rather than every consuming tree re-testing the same mechanics — each of the 4
  trees then only needs to test its own grouping/ordering logic plus one
  integration test confirming it renders through the shared primitive correctly.
- `ImpactBar`/`TierRows` get a regression test against a >5-company fixture,
  confirming no visual/layout regression now that the cap is gone.
- Playwright visual verification (the standard for this project, given the two
  prior tree failures) across dark/light, mobile/desktop, and specifically a
  long-branch-list case (many sectors, or many companies in one time-horizon
  bucket) to confirm the tree scrolls cleanly rather than overflowing.

## Known pre-existing inconsistency (not in scope, flagging for awareness)

`index_tier`'s documented vocabulary disagrees across three files: `api.ts`'s
comment (`NIFTY50 | NIFTY100 | NIFTY500 | GLOBAL_LARGE_CAP | OTHER`),
`models.py`'s comment (`NIFTY50 | NIFTY100 | NIFTY500 | OTHER`, no
`GLOBAL_LARGE_CAP`), and `transforms.ts`'s actual `TIER_ORDER` array (`NIFTY50,
NIFTYNEXT50, NIFTYMIDCAP150, NIFTYSMALLCAP250, GLOBAL_LARGE_CAP, OTHER`). This
doesn't break anything today (`tierKey()` falls back to `'OTHER'` gracefully for
any unrecognized value), but the three comments should eventually be reconciled to
the real vocabulary. Out of scope for this spec since `TierRows` isn't being
touched this round.
