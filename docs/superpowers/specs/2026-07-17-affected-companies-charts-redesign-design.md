# Affected-Companies Charts Redesign — Design

## Goal

Redesign `AlertChartsPage` and its 7 chart components to match the two reference
mockups exactly (aesthetic, layout, card formation): a 10-chart set (image 1) and
a Normal View / Drilldown View page structure (image 2). This supersedes the
"deferred" boundary drawn in `2026-07-15-tree-graphs-v4-design.md`, which
explicitly held back Ripple Effect, Supply Chain, Economic Chain, Knowledge Graph,
and multi-level tiers beyond L2 over fabrication risk (LLM asserting
relationships/narratives not grounded in real data). This spec resolves that
boundary chart-by-chart rather than lifting it wholesale — see "Fabrication-risk
resolution" below.

## Chart inventory and data sourcing

| # | Chart | Component | Data source |
|---|---|---|---|
| 1 | Impact Tree | `LevelTree.tsx` (restyle) | real — `impact_level` |
| 2 | Ripple Effect Graph | `RippleEffectGraph.tsx` (new) | real — `impact_level` + `parent_company_id` |
| 3 | Supply Chain Graph | `SupplyChainGraph.tsx` (new) | **mock** — no supplier/customer field exists |
| 4 | Multi-Level Impact Tree | `TierRows.tsx` (restyle) | real — `impact_level` + `parent_company_id`, capped at L2 (model has no L3+) |
| 5 | Confidence Tree | `ConfidenceTree.tsx` (restyle) | real — `confidence_score` |
| 6 | Positive/Negative Split | `SplitTree.tsx` (restyle) | real — `direction` |
| 7 | Timeline Tree | `TimelineTree.tsx` (restyle) | real — `time_horizon` |
| 8 | Sector Tree | `SectorTree.tsx` (restyle) | real — `sector` |
| 9 | Economic Chain | `EconomicChain.tsx` (new) | real — **new** `Alert.economic_chain` field (LLM-generated, see below) |
| 10 | Knowledge Graph | `KnowledgeGraph.tsx` (new) | **mock** — no entity-relation field exists |

`ImpactBar.tsx` is retired (doesn't map to any of the 10 target charts).

## Fabrication-risk resolution

The v4 spec's deferral was correct at the time — these charts need data the
model didn't have. Each of the 4 previously-deferred chart types resolves
differently now:

- **Ripple Effect Graph**: no new risk. It's the same `impact_level` +
  `parent_company_id` hierarchy already used by Multi-Level Impact Tree, laid out
  radially instead of as rows. Both were already real, ungated data as of the v4
  spec's own writing — the deferral in that spec was about levels 3-5 and the
  *other* three chart types, not this one specifically re-litigated here.
- **Multi-Level Impact Tree**: capped at Level 2 (Direct → Indirect L1 → Indirect
  L2), matching what `impact_level`'s enum actually supports. The mockup's
  Level 3/4 rows are out of scope — would need new enum values and is a separate
  future decision, not silently fabricated by inventing extra tiers client-side.
- **Supply Chain Graph / Knowledge Graph**: still no real field for
  supplier/customer/entity relationships. Per explicit decision, these ship with
  clearly-marked **mock** data behind the same props interface a real field would
  use later, so swapping in real data is a data-layer change only, no UI rework.
  Mock data lives in a dedicated `mockRelations.ts` (or similar) module, never
  mixed into `transforms.ts`'s real-data helpers, so it can't accidentally get
  treated as real.
- **Economic Chain**: per explicit decision, gets a real new LLM-generated field
  (below) rather than mock — this is the one chart type getting new backend work
  in this project, with its own anti-fabrication guardrail baked into the prompt
  rule itself (empty-list escape hatch, grounding requirement, fixed vocabulary).

## New backend field: `Alert.economic_chain`

Alert-level (not per-company) — precedent is `event_type`, the one existing
alert-level LLM field (`RECORD_ANALYSIS_TOOL`'s top-level properties, not nested
under `companies.items`).

### Schema

`backend/app/analysis/schemas.py`, new type alongside `CompanyMention`:

```python
ECONOMIC_CHAIN_VARIABLES = {
    "interest_rates", "borrowing_costs", "consumer_spending",
    "corporate_earnings", "inflation", "currency", "trade_balance",
    "government_revenue", "employment", "stock_market_impact",
}

class EconomicChainStep(BaseModel):
    variable: str        # validated against ECONOMIC_CHAIN_VARIABLES
    direction: str        # "up" | "down"
    time_horizon: str     # validated against existing TIME_HORIZONS
    rationale: str         # one sentence, grounded in this article
```

`AnalysisOutput` gains `economic_chain: list[EconomicChainStep] = []` — default
empty, same "existing callers without the feature still validate" pattern as
`CompanyMention`'s list fields.

### Storage

`backend/app/models.py`, new `Alert.economic_chain_json` (`Text`, `nullable=True`)
— same one-column-per-field, JSON-encoded-text pattern as
`AlertCompany.reasons_json` etc., not SQLAlchemy's `JSON` type (matches existing
convention). Encoded/decoded in `backend/app/pipeline.py` alongside the other
`_json` columns; decoding here is `json.loads` directly (list of dicts, not
`_decode_json_list`'s `list[str]` shape) since each step is a structured object.

### Prompt rule

`backend/app/analysis/claude_client.py`, new rule 18 (after the existing 17),
following rule 9's event-level framing:

> Classify this article's macro economic transmission chain as
> `economic_chain`: an ordered list of 3-6 steps showing how this event's effect
> propagates through the broader economy over time, from immediate mechanism to
> eventual stock-market impact. Each step names one `variable` from the fixed
> vocabulary [...], a `direction` (up/down), the `time_horizon` it plays out over
> (same Immediate/Short-Term/Medium-Term/Long-Term vocabulary as company-level
> `time_horizon`), and a one-sentence `rationale` grounded in this specific
> article — not generic macro theory. The final step should normally be
> `stock_market_impact`. **Leave this an empty list if the article's effect is
> too narrow or company-specific to support a genuine macro chain** — do not
> fabricate a chain for a purely idiosyncratic single-company event (e.g. a
> product recall, an executive resignation).

The empty-list escape hatch is the guardrail: most alerts (single-company,
narrow) legitimately produce `[]`, and `EconomicChain.tsx` renders an explicit
"This event's chain of macro effects wasn't broad enough to call out" empty
state rather than coercing something out of nothing — same philosophy as this
project's existing confidence/calibration-first approach.

`RECORD_ANALYSIS_TOOL`: `economic_chain` added as a top-level tool property
(alongside `category`/`event_type`), array of objects matching
`EconomicChainStep`, not required, defaults to `[]`.

### API and frontend types

`_serialize_alert` (`backend/app/routers/alerts.py`): add
`"economic_chain": alert.economic_chain or []` to the outer dict, next to
`event_type`.

`frontend/src/lib/api.ts`'s `Alert` interface: add
`economic_chain?: EconomicChainStep[]` next to `event_type?`, with a matching
`EconomicChainStep` TS interface (`variable`, `direction`, `time_horizon`,
`rationale`). `WsAlert` inherits it automatically (already `Omit<Alert,
'companies'> & {...}`).

### Verification

New LLM output needs the same real-article verification pass the v4 spec
required for its own prompt change: run against a sample of recent real
articles, confirm (a) narrow single-company articles correctly produce `[]`
rather than a fabricated chain, (b) broad macro articles (rate changes, tariffs,
commodity moves) produce a plausible, well-grounded 3-6 step chain, (c) no
cost/latency regression from the added tool property.

## Shared visual system

### `ChartCardShell` (new, `frontend/src/features/visualize/charts/ChartCardShell.tsx`)

Every one of the 10 charts wraps in this shell, replacing today's inconsistent
per-chart headers:

- Numbered circle badge (1-10, per the image-1 grid position) + chart title +
  one-line description, matching image 1's header row exactly.
- Dark card container (`bg-surface`, existing token), consistent padding/radius
  with the rest of the app.
- News context strip: article title + timestamp, reusing existing header data
  already fetched by `AlertChartsPage` (no new fetch).
- Legend strip pinned to the card bottom (e.g. "Positive Impact / Negative
  Impact / Neutral Impact" swatches), color source varies per chart
  (`impactLevelColor`, `sectorColor`, `confidenceColor`, or a chart-specific
  legend as appropriate) but the shell's legend layout is shared.

### Color additions (`colors.ts` / `impactLevels.ts`)

- Tier-level colors (direct/L1/L2) already exist (`IMPACT_LEVEL_COLOR`) — reused
  as-is for Impact Tree, Ripple Effect, Multi-Level Tree.
- Confidence ramp already exists (`CONFIDENCE_RAMP`) — reused as-is.
- New: a small fixed palette for Economic Chain's `variable` vocabulary (10
  values) and direction glyph (up/down arrow, reusing `bullish`/`bearish`
  tokens) — validated with the `dataviz` skill's palette validator the same way
  `SECTOR_COLOR`/`CONFIDENCE_RAMP` were, before shipping.
- New: mock-data relation-type colors for Supply Chain (Supplier/Direct/
  Customer/End User, per image 1's legend) and Knowledge Graph (Supply
  Chain/Competition/Partnership/Regulatory/Market, per image 1's legend) —
  same validation requirement.

## Page redesign: `AlertChartsPage.tsx`

### Normal View (image 2, left panel)

- Header: back button, article title + timestamp + category/region tags,
  "Drilldown View →" toggle button (top-right).
- Stat tile row (4 tiles): Overall Impact (direction + confidence %), Affected
  Sectors (count), Affected Categories (count), Affected Companies (count) —
  `StatBar` component already exists, restyled to match image 2's tile look
  (icon + label + big number).
- "Directly Affected Sectors" card grid: one card per sector present among
  `impact_level === 'direct'` companies — icon, sector name, direction badge
  (High/Medium/Low + Positive/Negative), one-line mechanism description, ticker
  list with live % change, "View Details →" link. This is new — no existing
  component does this card-grid-of-sectors layout; built fresh, reusing
  `groupBySector`/`sectorColor`.
- "Impact Summary" banner (bottom): one-paragraph synthesis + "View Full
  Analysis →" link. Synthesis text: if `economic_chain` non-empty, use its
  rationale chain to compose the summary; else fall back to today's existing
  summary text source.

### Drilldown View (image 2, right panel)

- Same header, toggle now reads "← Normal View".
- Tiered flow instead of stat tiles: Direct Impact → Indirect L1 → Indirect L2
  rows (capped at L2, per the data-model note above — the mockup's L3+ row is
  out of scope), each row showing category boxes with company counts, connected
  by arrows. "Expand All" / "Collapse All" controls in the header row.
- Same card-grid-of-categories pattern as Normal View but per indirect level,
  reusing the same sector/category card component parameterized by
  `impact_level`.
- "Full Impact Summary" banner (bottom), same synthesis logic as Normal View's
  Impact Summary but covering all levels, not just direct.

The existing `Breadth = 'normal' | 'drilldown'` toggle state is kept — this is a
visual rebuild of both views, not new state logic.

### Chart tab strip

Restyled to numbered pills matching image 1's grid order (1 Impact Tree ... 10
Knowledge Graph), horizontally scrollable, same swipe interaction as today.

## Per-chart component plan

Restyle (data/logic unchanged, wrap in `ChartCardShell`, apply new visual
language): `LevelTree`, `TierRows`, `ConfidenceTree`, `SplitTree`,
`TimelineTree`, `SectorTree`.

New:
- `RippleEffectGraph.tsx` — circular/radial layout, center node = news event,
  ring 1 = direct companies, ring 2 = their `parent_company_id`-linked
  indirect_l1 companies, connecting lines colored by impact-level color. Plain
  HTML/CSS positioning (absolute-positioned nodes in a fixed-size circle),
  consistent with this codebase's established "no SVG node-link diagrams"
  lesson from the v4 spec (canvas/SVG connector math caused two prior failed
  attempts) — connectors here are straight `border`-based lines between fixed
  grid positions, not computed curves.
- `EconomicChain.tsx` — linear horizontal (desktop) / vertical (mobile) step
  flow, one box per `economic_chain` entry, arrow connectors, direction glyph +
  time_horizon label per box, empty state as described above.
- `SupplyChainGraph.tsx` — three-column layout (Upstream/Suppliers → Direct
  Company → Downstream/Customers), mock data.
- `KnowledgeGraph.tsx` — center node = news event, radial category nodes
  (Suppliers/Competitors/Customers/Regulators/Countries/Commodities/Sectors/
  ETFs/Indices/Events) each with a mock count badge, mock data.

## Testing

- Backend: unit tests for `EconomicChainStep` validation (variable/direction/
  time_horizon enum enforcement), `_serialize_alert` including
  `economic_chain: []` for legacy alerts, `pipeline.py` encode/decode
  round-trip. Real-article verification pass per the "Verification" section
  above before considering the field done.
- Frontend: `ChartCardShell` gets its own test (badge/legend rendering) once,
  each chart's own test covers its grouping/ordering logic same as the v4
  spec's pattern. Mock-data charts (`SupplyChainGraph`, `KnowledgeGraph`) get a
  test asserting they render from the mock module without touching any real
  `Alert` field, so a future real-data swap can't silently regress into reading
  stale mock data.
- Playwright visual verification across dark/light, mobile/desktop for the
  container page (both views) and each new chart, per this project's established
  practice after two prior tree-chart visual failures.

## Rollout phases

1. `ChartCardShell` + color/legend additions (shared foundation).
2. `AlertChartsPage` container rebuild (Normal View + Drilldown View layout,
   stat tiles, sector-card grid, summary banners) — ships before individual
   chart restyles so the page shell is correct even with old chart internals
   temporarily mounted inside it.
3. Restyle the 6 existing charts into the new shell (parallelizable — each is
   an independent component).
4. Backend: `economic_chain` field, prompt rule, schema, verification pass.
5. New charts: `RippleEffectGraph`, `EconomicChain` (once backend field ships),
   `SupplyChainGraph`, `KnowledgeGraph` (mock) — parallelizable.
6. Retire `ImpactBar`.
