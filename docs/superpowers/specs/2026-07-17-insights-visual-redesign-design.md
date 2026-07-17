# Insights Visual Redesign — Design

## Goal

The reasoning/insights/analysis layer (the product's stated USP) is currently
too textual for the main "affected companies" feed — a wall of paragraphs per
company, unreadable at a glance. This redesign:

1. Replaces the feed's per-company block with a compact, scannable card that
   still conveys the real signal (direction, confidence, horizon, impact,
   one-sentence summary, a few more insights on demand).
2. Moves the full reasoning (currently `ReasoningPanel`'s inline-expandable
   "Why this call" section) to its own dedicated page, reachable via a
   "Read full analysis" link from the compact card.
3. Gives both a genuinely graphical, non-generic visual language — validated
   over many iterations in the visual companion, landing on an editorial
   research-note aesthetic (serif headline + monospace data, hairline rules,
   footnote-style citations) rather than the generic rounded-card/
   colored-border/emoji "AI dashboard" look that was explicitly rejected
   mid-session.
4. Adds real company logos (Brandfetch, client ID already obtained:
   `1id6a--idLiMmWBBFLu`) in place of the placeholder monogram.

## Current state (grounded in the actual code)

- `frontend/src/components/AlertCompanies.tsx` renders the affected-companies
  feed section for one alert: tabs, group-by selector, a `SentimentBar`, a
  "Charts →" button, and a grid of `CompanyChip` per company.
- `frontend/src/components/CompanyChip.tsx` is the collapsed row; clicking it
  toggles an inline-mounted `ReasoningPanel` (accordion pattern) — this is
  what makes the feed long: expanding one company inlines a full paragraph
  block without navigating away.
- `frontend/src/components/ReasoningPanel.tsx` already has all the data
  plumbing the "full analysis" page needs: key points, confidence-band pill,
  Facts section (price/return/contradiction), "Why this call" (reasons,
  evidence_refs via `formatEvidenceRef`, alternative_hypothesis, risks/
  assumptions/unknowns, confidence_contributors/penalties), past mentions,
  and a "View details" link to `/company/:id`. This redesign does not need
  to invent new data plumbing for the detail page — it restyles and
  relocates what `ReasoningPanel` already renders.
- `frontend/src/components/CompanyAvatar.tsx` is an explicitly-flagged
  placeholder (its own comment says so): a deterministic color+monogram, no
  real logo, because `AlertCompany` (the feed's per-company type) has no
  `logo_url` field. `Company`/`CompanyProfile` *do* have `logo_url`, built by
  `backend/app/routers/companies.py::_logo_url` from Brandfetch — that
  function needs to run for alert-companies too.
- `AlertCompany` (`frontend/src/lib/api.ts:22-73`) already carries every
  reasoning field this design needs: `confidence_score` (0-100),
  `time_horizon` (`Immediate | Short-Term | Medium-Term | Long-Term`),
  `impact_level` (`direct | indirect_l1 | indirect_l2`), `key_points:
  string[]`, `direction`, `reasons`/`evidence_refs`/`risks`/`assumptions`/
  `unknowns`/`alternative_hypothesis`/`confidence_contributors`/
  `confidence_penalties`, `price_at_analysis`/`return_1m`/`return_3m`/
  `contradiction_note`, `sector`, `ticker`. No new `AlertCompany` fields are
  needed for content — only `logo_url` is missing.
- There is **no relative-time formatter** anywhere in the codebase (verified:
  no date library installed, only absolute-format helpers exist in
  `AlertCoverCard.tsx`/`MentionRow.tsx`). The compact card's "2h ago" strip
  needs one written from scratch.
- The price-series endpoint (`GET /api/companies/{id}/prices`,
  `backend/app/routers/companies.py:113-119`) 404s for any company whose
  `market != "IN"` (`_get_indian_company_or_404`). The compact card's
  sparkline needs to work for `GLOBAL` companies too — `fetch_price_series`
  itself is not IN-specific (it's a yfinance wrapper, same one the financial
  grounding feature already uses uniformly across both markets per
  `docs/superpowers/specs/2026-07-16-financial-grounding-contradiction-
  detection-design.md`) — the IN-only restriction is a router-level policy
  choice, not a data limitation, and needs relaxing.
- Frontend routes (`App.tsx:28-50`) all use a single `:id` param (e.g.
  `/company/:id`, `/alerts/:id/charts`) even where the page internally calls
  it `companyId`/`alertId` — this redesign's new route follows that same
  `:id` convention.

## Visual language (locked)

Validated interactively in the visual companion across many rounds,
including one explicit rejection-and-redo ("looks extremely AI-made, change
the UI completely") — the accepted direction drops every generic-AI-dashboard
tell (rounded cards, colored left-borders, emoji icons, soft glows, rainbow
color-coding) in favor of an editorial research-note look:

- **Fonts:** `Newsreader` (serif, variable optical sizing) for company name,
  card summary sentence, and the detail page's prose — `IBM Plex Mono` for
  every number, label, ticker, timestamp, and footnote. Both loaded via
  Google Fonts `@import`. This pairing replaces the app's current plain
  `Georgia`/system-sans `fontFamily.display`/`fontFamily.sans` tokens in
  `tailwind.config.ts` for this feature's surfaces — the rest of the app is
  unaffected (no global font swap in this design).
- **Color — dark theme (default):** uses the app's real CSS vars verbatim,
  no invented colors: `page #0A0A0A`, `surface #161616`, `hairline #262626`,
  `ink #F2F2F2`, `muted #8E8E93`, `bullish #34C759`, `bearish #FF453A`. Dark
  theme's own `accent` token already equals `ink` (an existing, intentional
  app-wide choice per `index.css`'s comment) — this design does not invent a
  separate accent color for dark mode; confidence-label emphasis and other
  "pop" moments use `bullish` green (confidence is inherently a
  positive-framed metric) or plain `ink`, never a new hue.
- **Color — light theme:** uses the app's real light vars: `page #E4E8F1`,
  `surface #EDF0F7`, `hairline #D5DBE8`, `ink #3A3F52`, `muted #8891A8`, plus
  the app's actual `accent #635BFF` / `accent-secondary #2DD4BF` — light
  theme genuinely has these colors already, so unlike dark mode it's
  reasonable to use them for the same emphasis moments dark mode gives to
  `bullish` green.
- **Structural language:** hairline (1px) rules instead of card borders/
  shadows/border-radius-heavy boxes; footnote-style citations (superscript
  numerals ¹²³ + a small numbered list) instead of colored "evidence card"
  boxes; an italic, left-rule-indented blockquote for the alternative
  hypothesis instead of a dashed colored callout box.
- **Iconography:** kept intentionally minimal and custom, not a generic icon
  pack or emoji: a five-dot confidence meter (filled count = confidence
  band), a pie-slice glyph for time horizon (◔/◑/etc., see mapping below),
  and plain mono text (no icon) for impact level.

## Compact card (feed default view)

Replaces `CompanyChip`'s collapsed row + inline `ReasoningPanel` expansion.
One card per `AlertCompany`, stacked in a single-column feed (hairline rule
between cards, no card-in-card shadow) inside `AlertCompanies.tsx`.

**Structure, top to bottom:**

1. **Strip row** (mono, small, muted): `eventTypeLabel(alert.event_type) ·
   {sector title-cased}` on the left, relative time (`{N}h ago`, new utility
   — see below) on the right.
2. **Header row:** logo (44×44, 1px hairline border square, real
   `<img src={logo_url}>`; falls back to the existing `CompanyAvatar`
   monogram treatment — restyled to a plain bordered square with mono
   initials instead of a colored rounded box — on image load error or when
   `logo_url` is null) — company name (Newsreader, bold, 22px) and ticker+
   exchange (mono, muted) stacked next to it — price block right-aligned:
   direction arrow (▲/▼, `bullish`/`bearish` color) + `price_at_analysis`
   (mono, ₹ or $ per market) on one line, `return_1m` percentage below it in
   the same direction color. If `price_at_analysis` is null (no financial
   snapshot yet), the whole price block is omitted, not zero-filled.
3. **Chart row:** full-width SVG sparkline built from `getCompanyPrices`
   (extended to work for `GLOBAL` market — see Backend Changes), stroke
   color = direction color, with a faint dashed baseline at the first point's
   y-value so the viewer can see gain/loss against the start, not just the
   line's shape. If the price series is unavailable, the row is omitted.
4. **Gauges row:** three equal-width columns, each a 3-row grid (label →
   value → icon/meter), so all three columns' values sit on the same
   baseline regardless of whether that column has an icon:
   - **Confidence:** label "CONFIDENCE" in `bullish` green (dark) /
     `accent` (light) — value `{confidence_score}%` — five-dot meter,
     filled dots = `Math.round(confidence_score / 20)`.
   - **Horizon:** label "HORIZON" in muted — value = the enum's display text
     (`Immediate`/`Short`/`Medium`/`Long`, i.e. `time_horizon` with
     `-Term` stripped) — a pie-slice glyph mapped by urgency:
     `Immediate → ●`, `Short-Term → ◔`, `Medium-Term → ◑`, `Long-Term → ◯`.
   - **Impact:** label "IMPACT" in muted — value = `direct → "Direct"`,
     `indirect_l1 → "Indirect"`, `indirect_l2 → "Indirect · 2nd-order"` — no
     icon (empty grid cell, keeping the 3-row alignment intact).
5. **Summary:** one sentence, Newsreader serif, 16-19px. Source:
   `key_points[0]` if present; if `key_points` is empty (older alerts
   predating that field), fall back to a truncated `rationale` (first
   sentence, or first ~140 chars with an ellipsis).
6. **Footer row:** left side — `+{N} more insights` toggle, shown only when
   `key_points.length > 1`, `N = key_points.length - 1`; clicking it expands
   `key_points[1:]` inline as a plain bullet list directly below the summary
   (no navigation, matches the "brief, not another wall of text" goal — a
   handful of one-line points, not paragraphs) and the label flips to
   `▴ See less`, collapsing back on a second click. Right side — `Read full
   analysis →`, always shown, navigates to the new detail-page route.

## Full analysis page (detail view)

New route `/alerts/:id/company/:companyId` (follows the existing `:id`
single-param convention; the second param is genuinely a different resource
so it gets its own name, `:companyId`, matching how `/company/:id`'s page
internally calls its own param `companyId`). New page component
`frontend/src/pages/AlertCompanyAnalysisPage.tsx`.

This page is **not new data plumbing** — it restyles what `ReasoningPanel`
already renders (reasons, evidence_refs, risks, assumptions, unknowns,
alternative_hypothesis, confidence_contributors, confidence_penalties, Facts/
contradiction, past mentions), in the same editorial visual language as the
compact card, but showing everything (no truncation):

- Same header treatment as the compact card (logo, name, ticker, price,
  chart) at a larger size, plus the full confidence/horizon/impact gauge row.
- Confidence breakdown as a thin (2px) hairline-height segmented bar —
  segments sized by parsing `confidence_contributors`/`confidence_penalties`
  (already-computed weighted values from `app.reasoning.confidence`, not
  re-derived on the frontend) — labeled underneath in mono, not a thick
  glowing rounded bar.
- Full reasons + evidence as numbered footnotes: each `reasons[i]` gets a
  superscript marker inline (not applicable here since there's no single
  summary sentence to attach markers to on this page — instead render
  `reasons` as a numbered mono list, each followed by its matching
  `evidence_refs[i]` formatted via the existing `formatEvidenceRef`/
  `ruleLabel`/`formatTime`-style helpers already in `ruleLabels.ts`).
- `risks`/`assumptions`/`unknowns` as their own labeled mono lists (plain
  list items, not colored cards).
- `alternative_hypothesis` as the italic left-rule blockquote.
- Facts section (price/return_1m/return_3m/contradiction_note) reusing the
  existing data and copy from `ReasoningPanel`, restyled to mono/hairline.
- Past mentions (`MentionRow`) kept as-is functionally, restyled to fit.
- A back link to the feed (browser back is sufficient; no special state to
  preserve since the feed itself doesn't need to remember scroll position
  for this — standard SPA back-navigation).

`CompanyChip`/`ReasoningPanel`'s current inline-accordion usage inside
`AlertCompanies.tsx` is removed — the compact card replaces `CompanyChip`
entirely, and `ReasoningPanel`'s content moves to this page. `ReasoningPanel`
itself is deleted once its content is ported (not kept as unused dead code).
The existing `/company/:id` page's own "latest alert" summary usage is
unaffected — that page doesn't render `ReasoningPanel`, it renders its own
short summary already, per the earlier codebase survey.

## Backend changes

1. **`logo_url` on `AlertCompany`:** `backend/app/routers/alerts.py::
   _serialize_alert` (lines 25-62) builds each company dict inside a
   `for ac in alert.companies:` loop that already has `ac.company` (a real
   `Company` object, e.g. `ac.company.ticker`/`ac.company.name` are already
   read there) — add `"logo_url": _logo_url(ac.company)` to that dict. The
   `_logo_url` helper is currently private to `companies.py`
   (`backend/app/routers/companies.py:23-28`) — move it to a small shared
   module, `backend/app/companies/branding.py`, since it's a lookup both
   routers need, not really "a companies router concern"; both routers
   import it from there instead of one importing the other's private
   function.
2. **`BRANDFETCH_CLIENT_ID` env var:** set in Railway to
   `1id6a--idLiMmWBBFLu` (already obtained from the user). Without it,
   `_logo_url` returns `None` for everyone and every card falls back to the
   monogram — safe degrade, not a hard dependency for the rest of this
   design to ship.
3. **Relax `GET /api/companies/{id}/prices` to support `GLOBAL` market:**
   replace `_get_indian_company_or_404` at that endpoint with a lookup that
   accepts both markets (e.g. a plain `db.query(Company).get(company_id)` +
   404-if-None, dropping the `market == "IN"` filter) — `fetch_price_series`
   already works for any ticker yfinance recognizes, Indian or global, so
   this is a policy relaxation, not new integration work. Existing callers
   of this endpoint (`CompanyPage.tsx`) are IN-only today but nothing about
   them breaks if the endpoint also starts serving GLOBAL companies.

## New frontend utility

`frontend/src/lib/relativeTime.ts` — `formatRelativeTime(iso: string): string`.
Buckets: `< 60s → "just now"`, `< 60m → "{N}m ago"`, `< 24h → "{N}h ago"`,
`< 7d → "{N}d ago"`, `else` → fall back to the existing absolute-date style
already used by `AlertCoverCard.tsx`'s `formatTime` (reuse that function
rather than duplicating the `toLocaleString` call).

## Testing

- `relativeTime.ts`: pure function, unit tests for each bucket boundary
  (59s/60s, 59m/60m, 23h/24h, 6d/7d) with fixed `Date` inputs.
- Compact card component: rendering tests for the logo-fallback path (image
  `onerror` swaps to monogram), the confidence-dot count at boundary values
  (0%, 20%, 21%, 100%), each horizon glyph mapping, each impact-level label,
  the summary fallback when `key_points` is empty, and the see-more/see-less
  toggle's expand/collapse + label flip.
- Backend: `_logo_url` reuse at the alerts endpoint gets a test asserting
  the serialized alert includes `logo_url` matching the companies-endpoint's
  existing `_logo_url` test pattern. The relaxed prices endpoint gets a test
  confirming a `GLOBAL`-market company now returns 200 instead of 404 (reuse
  the existing IN-market prices test's mocking pattern for the new case).
- Detail page: rendering test confirming every `AlertCompany` reasoning
  field that has data actually appears (reasons count, evidence_refs count,
  risks/assumptions/unknowns lists, alternative_hypothesis presence,
  contradiction_note visual treatment when present vs absent).

## Explicitly out of scope

- `magnitude_low`/`magnitude_high` are not surfaced anywhere in this design
  (neither card nor detail page) — no visual treatment was validated for
  them in the companion; a future pass can add them if wanted.
- No changes to `/company/:id`'s own page content beyond nothing (it already
  has its own short summary, untouched by this design).
- No changes to `AlertChartsPage`/`/alerts/:id/charts` — that route's
  sector/impact-tree visualizations are a different, already-shipped
  feature, unrelated to per-company reasoning cards.
- Light-theme mockups were not separately re-validated screen-by-screen in
  the companion (all iteration happened against dark, the app's default) —
  this design specifies the exact light-theme token substitutions above, but
  the *first* implementation pass should get a real visual check in light
  mode before considering it done, not just a token swap taken on faith.
- Roadmap items 3-5 from the earlier reasoning-quality roadmap (pgvector
  historical retrieval, curated company relationship data, automated
  flywheel tuning) are untouched by this design.
