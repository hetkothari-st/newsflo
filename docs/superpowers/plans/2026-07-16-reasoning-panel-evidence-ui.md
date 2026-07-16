# Reasoning Panel Evidence UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the reasoning-engine backend fields (confidence band, reasons, evidence, risks/assumptions/unknowns, alternative hypothesis, confidence contributors/penalties, event type) in `ReasoningPanel`, reached via the feed (`CompanyChip`) and the confidence chart (`ConfidenceTree`).

**Architecture:** Extend the existing `AlertCompany`/`Alert` TypeScript interfaces with optional new fields (never breaking the ~27 files that already construct object literals of these types), add a small color/label lookup layer that reuses the existing validated confidence color ramp, and add one new collapsible section to `ReasoningPanel` gated on `reasons.length > 0` so legacy alerts render byte-identical to today.

**Tech Stack:** React + TypeScript, Tailwind CSS, Vitest + React Testing Library.

## Deviations from the design spec

1. **`AlertCompany`/`Alert` new fields are optional (`?:`), not required.** The
   design spec's TypeScript snippets showed them as required (`string | null`
   without `?`). TypeScript's structural typing requires every non-optional
   field to be present in every object literal, and ~27 files across the repo
   construct `AlertCompany`/`Alert` literals (test fixtures mostly). Making
   the new fields optional avoids updating any of them — the backend's own
   "safe default" lesson (Pydantic `Optional[...] = None`) applies here too,
   just via TS's `?:` instead.
2. **`event_type` is not wired into `ConfidenceTree`/`AlertChartsPage`.** All
   six chart types (`SectorTree`, `TierRows`, `ImpactBar`, `SplitTree`,
   `ConfidenceTree`, `TimelineTree`) are rendered through one shared
   `{ Component }` call site in `AlertChartsPage.tsx` with a single prop
   shape (`companies={visibleCompanies}`). Adding an `eventType` prop to only
   `ConfidenceTree` would force the other five (unrelated) chart components
   to also accept it for the shared call site to type-check. Given this is a
   minor line inside an already-collapsed section, `ReasoningPanel`'s new
   `eventType` prop is only threaded through the feed path
   (`AlertCompanies` → `CompanyChip` → `ReasoningPanel`), not the charts path.
   `ConfidenceTree`'s existing `<ReasoningPanel company={selected} />` call is
   untouched and keeps working — the event-type line just doesn't render
   there.
3. **Non-English translations for the new i18n keys ship as English text in
   every language slot for now, not real translations.** The catalog format
   requires an entry per `Language`, but authoring accurate Hindi / Marathi /
   Gujarati / Malayalam / Telugu / Tamil / Kannada / Punjabi / Bengali
   translations for new financial-UI terminology without native-speaker
   review risks shipping wrong text to real users of a live app — worse than
   shipping honest English. `translate()`'s own fallback
   (`entry?.[lang] ?? entry?.en ?? key`) already handles a missing key
   gracefully, so this is functionally identical to that fallback path,
   just made explicit with a comment instead of relying on a runtime
   fallback. Real translations are a disclosed follow-up, not hidden scope.

## Global Constraints

- `AlertCompany`/`Alert` new fields: optional, matching what the backend
  actually returns for legacy rows — `string[]` fields default to `[]`
  (never `undefined` from the API, but typed to tolerate it since the field
  itself is optional), `confidence_band`/`alternative_hypothesis`/`event_type`
  are `string | null` when present.
- Reuse the existing validated `CONFIDENCE_RAMP` in
  `frontend/src/features/visualize/colors.ts` for the confidence-band badge —
  no new color palette, no new dataviz-skill validation pass needed.
- `ReasoningPanel`'s new section renders only when `company.reasons` is
  non-empty — a legacy alert (no `reasons`) must render pixel-identical to
  today. This is verified by an explicit regression test in Task 6.
- Match existing test style exactly: Vitest + React Testing Library, the
  `render()` wrapper pattern (`MemoryRouter` + `LanguageProvider`) already
  used in `ReasoningPanel.test.tsx`/`CompanyChip.test.tsx`/
  `ConfidenceTree.test.tsx`, `screen.getByText`/`getByRole` assertions.

---

### Task 1: Extend TypeScript types

**Files:**
- Modify: `frontend/src/lib/api.ts:22-52`

**Interfaces:**
- Produces: `AlertCompany` gains `confidence_band?: string | null`,
  `reasons?: string[]`, `evidence_refs?: string[]`, `risks?: string[]`,
  `assumptions?: string[]`, `unknowns?: string[]`,
  `alternative_hypothesis?: string | null`,
  `confidence_contributors?: string[]`, `confidence_penalties?: string[]`.
  `Alert` gains `event_type?: string | null`.

This task has no runtime behavior of its own (types only) — no test file.
Verification is that `npm run build` / `tsc --noEmit` (or whatever the
project's typecheck command is) still passes with zero errors across the
whole repo, proving no existing object literal broke.

- [ ] **Step 1: Edit the interfaces**

```ts
// frontend/src/lib/api.ts — replace the AlertCompany interface:
export interface AlertCompany {
  company_id: number;
  ticker: string;
  name: string;
  index_tier: string; // NIFTY50 | NIFTY100 | NIFTY500 | GLOBAL_LARGE_CAP | OTHER
  sector?: string;
  direction: string; // bullish | bearish
  magnitude_low: number;
  magnitude_high: number;
  rationale: string;
  key_points: string[]; // short, scannable version of `rationale` -- empty for legacy alerts
  confidence_score: number; // 0-100, how directly evidenced this company's call is
  time_horizon: string; // Immediate | Short-Term | Medium-Term | Long-Term
  basis: string; // direct_mention | sector_inference
  confidence: string; // llm_estimate | calibrated
  market: 'IN' | 'GLOBAL';
  in_my_holdings: boolean;
  past_mentions: PastMention[]; // this company's prior alerts, most recent first
  // Reasoning-engine fields (see docs/superpowers/specs/2026-07-15-
  // reasoning-engine-upgrade-design.md). Optional because ~27 existing test
  // fixtures construct AlertCompany literals without them -- a legacy alert
  // (persisted before this feature shipped) also genuinely has none of
  // these, degrading to undefined/null exactly like a pre-feature alert.
  confidence_band?: string | null; // LOW | MODERATE | HIGH | VERY_HIGH | null
  reasons?: string[];
  evidence_refs?: string[];
  risks?: string[];
  assumptions?: string[];
  unknowns?: string[];
  alternative_hypothesis?: string | null;
  confidence_contributors?: string[];
  confidence_penalties?: string[];
}
```

```ts
// frontend/src/lib/api.ts — replace the Alert interface:
export interface Alert {
  id: number;
  // Raw, canonical, untranslated category slug -- used for watchlist
  // matching and swatch-color lookup. Never render this directly in a
  // non-English UI; use `category_label` for display.
  category: string;
  category_label: string;
  created_at: string;
  article: AlertArticle;
  companies: AlertCompany[];
  // Optional: legacy alerts (persisted before this feature shipped) have
  // no event_type.
  event_type?: string | null;
}
```

- [ ] **Step 2: Typecheck the whole frontend**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors (confirms the new optional fields didn't break any of
the ~27 files constructing `AlertCompany`/`Alert` literals).

- [ ] **Step 3: Run the full frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: all existing tests still pass (this task changes types only, no
runtime code).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add reasoning-engine fields to AlertCompany/Alert types"
```

---

### Task 2: Confidence band color

**Files:**
- Modify: `frontend/src/features/visualize/colors.ts`
- Test: `frontend/src/features/visualize/colors.test.ts`

**Interfaces:**
- Consumes: `confidenceColor(score: number): string` (existing,
  `frontend/src/features/visualize/colors.ts:59-62`)
- Produces: `confidenceBandColor(band: string): string`

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/features/visualize/colors.test.ts`:

```ts
import { confidenceBandColor } from './colors';

describe('confidenceBandColor', () => {
  it('returns a hex color string for every known band', () => {
    for (const band of ['LOW', 'MODERATE', 'HIGH', 'VERY_HIGH']) {
      expect(confidenceBandColor(band)).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it('is monotonic: LOW < MODERATE < HIGH < VERY_HIGH on the same ramp', () => {
    const RAMP_ORDER = ['#6F9EE4', '#5C8ACE', '#4976B9', '#3763A4', '#25508F'];
    const indices = ['LOW', 'MODERATE', 'HIGH', 'VERY_HIGH'].map((band) =>
      RAMP_ORDER.indexOf(confidenceBandColor(band)),
    );
    for (let i = 1; i < indices.length; i++) {
      expect(indices[i]).toBeGreaterThan(indices[i - 1]);
    }
  });

  it('falls back to the MODERATE color for an unrecognized band string', () => {
    expect(confidenceBandColor('not_a_real_band')).toBe(confidenceBandColor('MODERATE'));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/colors.test.ts`
Expected: FAIL with `confidenceBandColor is not exported` / not a function

- [ ] **Step 3: Implement confidenceBandColor**

Append to `frontend/src/features/visualize/colors.ts`:

```ts
// Reuses the same validated CONFIDENCE_RAMP as confidenceColor -- rather
// than validating a second palette for the 4-value band enum, each band
// maps to one representative point on the already-validated 0-100 ramp.
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

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/colors.test.ts`
Expected: PASS (all tests in the file, including the 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/colors.ts frontend/src/features/visualize/colors.test.ts
git commit -m "feat: add confidenceBandColor reusing the validated confidence ramp"
```

---

### Task 3: Rule and event-type label lookups

**Files:**
- Create: `frontend/src/lib/ruleLabels.ts`
- Test: `frontend/src/lib/ruleLabels.test.ts`

**Interfaces:**
- Produces: `ruleLabel(ref: string): string`, `eventTypeLabel(type: string): string`,
  `formatEvidenceRef(ref: string): { text: string; kind: 'rule' | 'article' | 'historical' | 'other' }`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/ruleLabels.test.ts
import { describe, expect, it } from 'vitest';
import { eventTypeLabel, formatEvidenceRef, ruleLabel } from './ruleLabels';

describe('ruleLabel', () => {
  it('returns a human label for a known rule id', () => {
    expect(ruleLabel('RULE_REPO_RATE_CUT')).toBe('Repo rate cut');
  });

  it('falls back to the raw id for an unrecognized rule id', () => {
    expect(ruleLabel('RULE_DOES_NOT_EXIST')).toBe('RULE_DOES_NOT_EXIST');
  });
});

describe('eventTypeLabel', () => {
  it('returns a human label for a known event type', () => {
    expect(eventTypeLabel('crude_oil')).toBe('Crude oil');
  });

  it('falls back to the raw value for an unrecognized event type', () => {
    expect(eventTypeLabel('not_a_real_event')).toBe('not_a_real_event');
  });
});

describe('formatEvidenceRef', () => {
  it('formats a rule id as kind "rule" with its human label', () => {
    expect(formatEvidenceRef('RULE_CRUDE_OIL_UP')).toEqual({ text: 'Crude oil up', kind: 'rule' });
  });

  it('formats an "article:" prefix as kind "article" with the prefix stripped', () => {
    expect(formatEvidenceRef('article: crude prices spiked 8% overnight')).toEqual({
      text: 'crude prices spiked 8% overnight',
      kind: 'article',
    });
  });

  it('formats a "historical:" prefix as kind "historical" with the prefix stripped', () => {
    expect(formatEvidenceRef('historical: 2019 repo cut lifted HDFC Bank credit growth')).toEqual({
      text: '2019 repo cut lifted HDFC Bank credit growth',
      kind: 'historical',
    });
  });

  it('formats anything else as kind "other" verbatim', () => {
    expect(formatEvidenceRef('some free-text evidence')).toEqual({
      text: 'some free-text evidence',
      kind: 'other',
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/ruleLabels.test.ts`
Expected: FAIL with `Failed to resolve import "./ruleLabels"`

- [ ] **Step 3: Implement ruleLabels.ts**

```ts
// frontend/src/lib/ruleLabels.ts
// Human-readable labels for rule ids (backend/app/reasoning/rulebook.py)
// and event types (backend/app/analysis/schemas.py::EVENT_TYPES). Kept in
// sync manually -- the frontend can't import backend Python, so this is a
// deliberate duplication, same tradeoff the backend itself makes between
// app/reasoning/confidence.py and app/calibration/blender.py for
// CALIBRATION_SAMPLE_THRESHOLD.

const RULE_LABELS: Record<string, string> = {
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

const EVENT_TYPE_LABELS: Record<string, string> = {
  repo_rate_change: 'Repo rate change',
  inflation: 'Inflation',
  crude_oil: 'Crude oil',
  currency_move: 'Currency move',
  government_spending: 'Government spending',
  earnings: 'Earnings',
  merger_acquisition: 'Merger/acquisition',
  banking_metrics: 'Banking metrics',
  other: 'Other',
};

export function eventTypeLabel(type: string): string {
  return EVENT_TYPE_LABELS[type] ?? type;
}

export type EvidenceRefKind = 'rule' | 'article' | 'historical' | 'other';

export function formatEvidenceRef(ref: string): { text: string; kind: EvidenceRefKind } {
  if (ref.startsWith('RULE_')) {
    return { text: ruleLabel(ref), kind: 'rule' };
  }
  if (ref.startsWith('article:')) {
    return { text: ref.slice('article:'.length).trim(), kind: 'article' };
  }
  if (ref.startsWith('historical:')) {
    return { text: ref.slice('historical:'.length).trim(), kind: 'historical' };
  }
  return { text: ref, kind: 'other' };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/ruleLabels.test.ts`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/ruleLabels.ts frontend/src/lib/ruleLabels.test.ts
git commit -m "feat: add rule/event-type label lookups for evidence display"
```

---

### Task 4: ConfidenceBandPill component

**Files:**
- Create: `frontend/src/components/ConfidenceBandPill.tsx`
- Test: `frontend/src/components/ConfidenceBandPill.test.tsx`

**Interfaces:**
- Consumes: `confidenceBandColor` from `../features/visualize/colors` (Task 2)
- Produces: `ConfidenceBandPill` component, props `{ band: string | null | undefined }`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/ConfidenceBandPill.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ConfidenceBandPill from './ConfidenceBandPill';
import { LanguageProvider } from '../lib/language';
import { confidenceBandColor } from '../features/visualize/colors';

function renderPill(band: string | null | undefined) {
  return render(
    <LanguageProvider>
      <ConfidenceBandPill band={band} />
    </LanguageProvider>,
  );
}

describe('ConfidenceBandPill', () => {
  it('renders the HIGH label colored via confidenceBandColor', () => {
    renderPill('HIGH');
    const el = screen.getByText('High');
    expect(el).toHaveStyle({ color: confidenceBandColor('HIGH') });
  });

  it('renders the VERY_HIGH label as "Very High"', () => {
    renderPill('VERY_HIGH');
    expect(screen.getByText('Very High')).toBeInTheDocument();
  });

  it('renders nothing for a null band (legacy alert)', () => {
    const { container } = renderPill(null);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for an undefined band', () => {
    const { container } = renderPill(undefined);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/ConfidenceBandPill.test.tsx`
Expected: FAIL with `Failed to resolve import "./ConfidenceBandPill"`

- [ ] **Step 3: Implement ConfidenceBandPill**

```tsx
// frontend/src/components/ConfidenceBandPill.tsx
import { confidenceBandColor } from '../features/visualize/colors';
import { useLanguage } from '../lib/language';
import type { TranslationKey } from '../lib/i18n';

const BAND_LABEL_KEY: Record<string, TranslationKey> = {
  LOW: 'reasoning.confidenceLow',
  MODERATE: 'reasoning.confidenceModerate',
  HIGH: 'reasoning.confidenceHigh',
  VERY_HIGH: 'reasoning.confidenceVeryHigh',
};

export default function ConfidenceBandPill({ band }: { band: string | null | undefined }) {
  const { t } = useLanguage();
  if (!band) return null;
  const labelKey = BAND_LABEL_KEY[band];
  if (!labelKey) return null;
  const color = confidenceBandColor(band);
  return (
    <span
      className="ml-1.5 inline-flex items-center rounded-full border-[1.5px] px-2 py-0.5 text-[10px] uppercase tracking-widest"
      style={{ borderColor: color, color }}
    >
      {t(labelKey)}
    </span>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/ConfidenceBandPill.test.tsx`
Expected: FAIL — the `reasoning.confidence*` translation keys don't exist
yet (Task 5 adds them), so `t(labelKey)` returns the raw key string
(`translate`'s fallback: `entry?.[lang] ?? entry?.en ?? key`), not "High"/
"Very High". This is expected at this point in the plan — do not add the
keys here; Task 5 does that and this test passes once Task 5 lands. Note
this in your step-4 report rather than treating it as a blocker.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ConfidenceBandPill.tsx frontend/src/components/ConfidenceBandPill.test.tsx
git commit -m "feat: add ConfidenceBandPill component (depends on Task 5 i18n keys)"
```

---

### Task 5: i18n keys

**Files:**
- Modify: `frontend/src/lib/i18n.ts`

**Interfaces:**
- Produces: new `TranslationKey` values: `reasoning.whyThisCall`,
  `reasoning.reasoningHeading`, `reasoning.evidenceHeading`,
  `reasoning.alternativeView`, `reasoning.risksAndUnknowns`,
  `reasoning.confidenceBreakdown`, `reasoning.eventType` (takes a `{type}`
  var), `reasoning.confidenceLow`, `reasoning.confidenceModerate`,
  `reasoning.confidenceHigh`, `reasoning.confidenceVeryHigh`

- [ ] **Step 1: Add the new catalog entries**

Insert into the `CATALOG` object in `frontend/src/lib/i18n.ts`, immediately
after the existing `'reasoning.viewDetails'` entry (`i18n.ts:417-421`):

```ts
  // English shown for every language slot below -- these are new keys with
  // no native-speaker review yet (see docs/superpowers/plans/2026-07-16-
  // reasoning-panel-evidence-ui.md's "Deviations" section). translate()'s
  // own fallback (entry?.[lang] ?? entry?.en ?? key) would produce the same
  // visible result if these per-language keys were simply omitted; they're
  // spelled out explicitly here so the catalog's shape stays consistent
  // with every other entry. Replace with real translations once reviewed.
  'reasoning.whyThisCall': {
    en: 'Why this call', hi: 'Why this call', mr: 'Why this call', gu: 'Why this call',
    ml: 'Why this call', te: 'Why this call', ta: 'Why this call', kn: 'Why this call',
    pa: 'Why this call', bn: 'Why this call',
  },
  'reasoning.reasoningHeading': {
    en: 'Reasoning', hi: 'Reasoning', mr: 'Reasoning', gu: 'Reasoning',
    ml: 'Reasoning', te: 'Reasoning', ta: 'Reasoning', kn: 'Reasoning',
    pa: 'Reasoning', bn: 'Reasoning',
  },
  'reasoning.evidenceHeading': {
    en: 'Evidence', hi: 'Evidence', mr: 'Evidence', gu: 'Evidence',
    ml: 'Evidence', te: 'Evidence', ta: 'Evidence', kn: 'Evidence',
    pa: 'Evidence', bn: 'Evidence',
  },
  'reasoning.alternativeView': {
    en: 'Alternative view', hi: 'Alternative view', mr: 'Alternative view', gu: 'Alternative view',
    ml: 'Alternative view', te: 'Alternative view', ta: 'Alternative view', kn: 'Alternative view',
    pa: 'Alternative view', bn: 'Alternative view',
  },
  'reasoning.risksAndUnknowns': {
    en: 'Risks & unknowns', hi: 'Risks & unknowns', mr: 'Risks & unknowns', gu: 'Risks & unknowns',
    ml: 'Risks & unknowns', te: 'Risks & unknowns', ta: 'Risks & unknowns', kn: 'Risks & unknowns',
    pa: 'Risks & unknowns', bn: 'Risks & unknowns',
  },
  'reasoning.confidenceBreakdown': {
    en: 'Confidence breakdown', hi: 'Confidence breakdown', mr: 'Confidence breakdown', gu: 'Confidence breakdown',
    ml: 'Confidence breakdown', te: 'Confidence breakdown', ta: 'Confidence breakdown', kn: 'Confidence breakdown',
    pa: 'Confidence breakdown', bn: 'Confidence breakdown',
  },
  'reasoning.eventType': {
    en: 'Event: {type}', hi: 'Event: {type}', mr: 'Event: {type}', gu: 'Event: {type}',
    ml: 'Event: {type}', te: 'Event: {type}', ta: 'Event: {type}', kn: 'Event: {type}',
    pa: 'Event: {type}', bn: 'Event: {type}',
  },
  'reasoning.confidenceLow': {
    en: 'Low', hi: 'Low', mr: 'Low', gu: 'Low', ml: 'Low', te: 'Low', ta: 'Low', kn: 'Low',
    pa: 'Low', bn: 'Low',
  },
  'reasoning.confidenceModerate': {
    en: 'Moderate', hi: 'Moderate', mr: 'Moderate', gu: 'Moderate', ml: 'Moderate', te: 'Moderate',
    ta: 'Moderate', kn: 'Moderate', pa: 'Moderate', bn: 'Moderate',
  },
  'reasoning.confidenceHigh': {
    en: 'High', hi: 'High', mr: 'High', gu: 'High', ml: 'High', te: 'High', ta: 'High', kn: 'High',
    pa: 'High', bn: 'High',
  },
  'reasoning.confidenceVeryHigh': {
    en: 'Very High', hi: 'Very High', mr: 'Very High', gu: 'Very High', ml: 'Very High', te: 'Very High',
    ta: 'Very High', kn: 'Very High', pa: 'Very High', bn: 'Very High',
  },
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 3: Re-run Task 4's test file, now that the keys exist**

Run: `cd frontend && npx vitest run src/components/ConfidenceBandPill.test.tsx`
Expected: PASS (all 4 tests — the "High"/"Very High" text assertions now
resolve to real catalog entries instead of the raw key fallback)

- [ ] **Step 4: Run the full frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/i18n.ts
git commit -m "feat: add i18n keys for reasoning panel evidence UI"
```

---

### Task 6: ReasoningPanel — badge and expandable evidence section

**Files:**
- Modify: `frontend/src/components/ReasoningPanel.tsx`
- Modify: `frontend/src/components/ReasoningPanel.test.tsx`

**Interfaces:**
- Consumes: `ConfidenceBandPill` (Task 4), `formatEvidenceRef` from
  `../lib/ruleLabels` (Task 3), `eventTypeLabel` from `../lib/ruleLabels`
  (Task 3)
- Produces: `ReasoningPanel` gains a second, optional prop:
  `eventType?: string | null` (default not passed → `undefined`,
  event-type line simply doesn't render — `ConfidenceTree`'s existing call
  site, `<ReasoningPanel company={selected} />`, needs no change)

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/ReasoningPanel.test.tsx`:

```tsx
describe('ReasoningPanel evidence section', () => {
  const withEvidence: AlertCompany = {
    ...base,
    confidence_band: 'HIGH',
    reasons: ['Refining margins widen on crude spike.'],
    evidence_refs: ['RULE_CRUDE_OIL_UP', 'article: crude jumped 8% overnight'],
    risks: ['Margin reversal if crude falls back.'],
    assumptions: ['Crude stays elevated for the quarter.'],
    unknowns: ['Whether this is a durable shock or a spike.'],
    alternative_hypothesis: 'Market has already priced this in.',
    confidence_contributors: ['Matched a known rulebook rule'],
    confidence_penalties: ['No historical calibration yet'],
  };

  it('renders no evidence section and no confidence badge for a legacy alert (reasons empty)', () => {
    render(<ReasoningPanel company={base} />);
    expect(screen.queryByText('Why this call')).not.toBeInTheDocument();
    expect(screen.queryByText('High')).not.toBeInTheDocument();
  });

  it('renders the confidence band badge when confidence_band is set', () => {
    render(<ReasoningPanel company={withEvidence} />);
    expect(screen.getByText('High')).toBeInTheDocument();
  });

  it('shows a "Why this call" toggle that is collapsed by default', () => {
    render(<ReasoningPanel company={withEvidence} />);
    expect(screen.getByText('Why this call')).toBeInTheDocument();
    expect(screen.queryByText('Refining margins widen on crude spike.')).not.toBeInTheDocument();
  });

  it('expands to show reasons, evidence, alternative view, risks, and confidence breakdown', async () => {
    render(<ReasoningPanel company={withEvidence} />);
    await userEvent.click(screen.getByRole('button', { name: 'Why this call' }));

    expect(screen.getByText('Refining margins widen on crude spike.')).toBeInTheDocument();
    expect(screen.getByText('Crude oil up')).toBeInTheDocument(); // RULE_CRUDE_OIL_UP label
    expect(screen.getByText('crude jumped 8% overnight')).toBeInTheDocument(); // article: prefix stripped
    expect(screen.getByText('Market has already priced this in.')).toBeInTheDocument();
    expect(screen.getByText('Margin reversal if crude falls back.')).toBeInTheDocument();
    expect(screen.getByText('Crude stays elevated for the quarter.')).toBeInTheDocument();
    expect(screen.getByText('Whether this is a durable shock or a spike.')).toBeInTheDocument();
    expect(screen.getByText('Matched a known rulebook rule')).toBeInTheDocument();
    expect(screen.getByText('No historical calibration yet')).toBeInTheDocument();
  });

  it('shows the event type line when eventType is passed', async () => {
    render(<ReasoningPanel company={withEvidence} eventType="crude_oil" />);
    await userEvent.click(screen.getByRole('button', { name: 'Why this call' }));
    expect(screen.getByText('Event: Crude oil')).toBeInTheDocument();
  });

  it('omits the event type line when eventType is not passed', async () => {
    render(<ReasoningPanel company={withEvidence} />);
    await userEvent.click(screen.getByRole('button', { name: 'Why this call' }));
    expect(screen.queryByText(/^Event:/)).not.toBeInTheDocument();
  });

  it('omits the alternative view line when alternative_hypothesis is null', async () => {
    render(<ReasoningPanel company={{ ...withEvidence, alternative_hypothesis: null }} eventType={null} />);
    await userEvent.click(screen.getByRole('button', { name: 'Why this call' }));
    expect(screen.queryByText('Alternative view')).not.toBeInTheDocument();
  });
});
```

Add `import userEvent from '@testing-library/user-event';` to the top of
`frontend/src/components/ReasoningPanel.test.tsx` (not already imported
there — check first, since `CompanyChip.test.tsx` imports it but
`ReasoningPanel.test.tsx` currently does not).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/ReasoningPanel.test.tsx`
Expected: FAIL — none of the new UI exists yet (no "Why this call" text, no
badge)

- [ ] **Step 3: Implement the ReasoningPanel changes**

```tsx
// frontend/src/components/ReasoningPanel.tsx
import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { AlertCompany } from '../lib/api';
import { precedentLine, splitRationaleIntoPoints } from '../lib/reasoning';
import { useLanguage } from '../lib/language';
import { eventTypeLabel, formatEvidenceRef } from '../lib/ruleLabels';
import ConfidenceBandPill from './ConfidenceBandPill';
import MentionRow from './MentionRow';

// Re-exported so this stays the one import path components/tests already use.
export { precedentLine, splitRationaleIntoPoints };

export default function ReasoningPanel({
  company,
  eventType,
}: {
  company: AlertCompany;
  eventType?: string | null;
}) {
  const { language, t } = useLanguage();
  const [whyOpen, setWhyOpen] = useState(false);
  // key_points is the model's own short, terse summary -- prefer it. Fall
  // back to sentence-splitting the full rationale only for alerts analyzed
  // before key_points existed (empty array).
  const points = company.key_points.length > 0 ? company.key_points : splitRationaleIntoPoints(company.rationale);
  const reasons = company.reasons ?? [];
  const evidenceRefs = company.evidence_refs ?? [];
  const caveats = [...(company.risks ?? []), ...(company.assumptions ?? []), ...(company.unknowns ?? [])];
  const contributors = company.confidence_contributors ?? [];
  const penalties = company.confidence_penalties ?? [];
  const hasEvidenceSection = reasons.length > 0;

  return (
    <div className="rounded-lg border border-hairline bg-surface px-3 py-3">
      <p className="flex items-center text-xs uppercase tracking-widest text-muted">
        {company.name} · {company.ticker}
        <ConfidenceBandPill band={company.confidence_band} />
      </p>
      <ul className="mt-2 space-y-1.5 text-sm text-ink">
        {points.map((point, i) => (
          <li key={i} className="flex gap-2">
            <span className="text-muted" aria-hidden="true">•</span>
            <span>{point}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">{precedentLine(company, language)}</p>
      {hasEvidenceSection && (
        <div className="mt-3 border-t border-hairline pt-2">
          <button
            type="button"
            onClick={() => setWhyOpen((v) => !v)}
            aria-expanded={whyOpen}
            className="flex items-center gap-1 text-xs uppercase tracking-widest text-ink"
          >
            <span aria-hidden="true">{whyOpen ? '▾' : '▸'}</span>
            {t('reasoning.whyThisCall')}
          </button>
          {whyOpen && (
            <div className="mt-2 flex flex-col gap-2.5 text-xs">
              <div>
                <p className="uppercase tracking-widest text-muted">{t('reasoning.reasoningHeading')}</p>
                <ul className="mt-1 space-y-1 text-ink">
                  {reasons.map((reason, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="text-muted" aria-hidden="true">•</span>
                      <span>{reason}</span>
                    </li>
                  ))}
                </ul>
              </div>
              {evidenceRefs.length > 0 && (
                <div>
                  <p className="uppercase tracking-widest text-muted">{t('reasoning.evidenceHeading')}</p>
                  <ul className="mt-1 space-y-1 text-ink">
                    {evidenceRefs.map((ref, i) => (
                      <li key={i}>{formatEvidenceRef(ref).text}</li>
                    ))}
                  </ul>
                </div>
              )}
              {company.alternative_hypothesis && (
                <div>
                  <p className="uppercase tracking-widest text-muted">{t('reasoning.alternativeView')}</p>
                  <p className="mt-1 italic text-ink">{company.alternative_hypothesis}</p>
                </div>
              )}
              {caveats.length > 0 && (
                <div>
                  <p className="uppercase tracking-widest text-muted">{t('reasoning.risksAndUnknowns')}</p>
                  <ul className="mt-1 space-y-1 text-ink">
                    {caveats.map((c, i) => (
                      <li key={i} className="flex gap-2">
                        <span className="text-muted" aria-hidden="true">•</span>
                        <span>{c}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {(contributors.length > 0 || penalties.length > 0) && (
                <div>
                  <p className="uppercase tracking-widest text-muted">{t('reasoning.confidenceBreakdown')}</p>
                  <ul className="mt-1 space-y-1">
                    {contributors.map((c, i) => (
                      <li key={`c-${i}`} className="flex gap-2 text-bullish">
                        <span aria-hidden="true">+</span>
                        <span>{c}</span>
                      </li>
                    ))}
                    {penalties.map((p, i) => (
                      <li key={`p-${i}`} className="flex gap-2 text-bearish">
                        <span aria-hidden="true">−</span>
                        <span>{p}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {eventType && (
                <p className="text-muted">
                  {t('reasoning.eventType', { type: eventTypeLabel(eventType) })}
                </p>
              )}
            </div>
          )}
        </div>
      )}
      {company.past_mentions.length > 0 && (
        <div className="mt-3 border-t border-hairline pt-2">
          <p className="text-xs uppercase tracking-widest text-muted">{t('reasoning.previously')}</p>
          <ul className="mt-1.5 space-y-1">
            {company.past_mentions.map((mention) => (
              <MentionRow key={mention.alert_id} mention={mention} />
            ))}
          </ul>
        </div>
      )}
      {company.market === 'IN' && (
        <Link
          to={`/company/${company.company_id}`}
          className="mt-3 inline-block text-xs uppercase tracking-widest text-ink underline"
        >
          {t('reasoning.viewDetails')}
        </Link>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/ReasoningPanel.test.tsx`
Expected: PASS (all tests, including every pre-existing test in the file —
none of them set `reasons`, so `hasEvidenceSection` is `false` for all of
them and the DOM they assert against is unchanged)

- [ ] **Step 5: Run the full frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: all tests pass (this also re-confirms `ConfidenceTree.test.tsx`
still passes unmodified, since its `<ReasoningPanel company={selected} />`
call doesn't pass `eventType` and none of its fixture companies set
`reasons`)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ReasoningPanel.tsx frontend/src/components/ReasoningPanel.test.tsx
git commit -m "feat: add confidence badge and evidence section to ReasoningPanel"
```

---

### Task 7: Thread eventType through the feed path

**Files:**
- Modify: `frontend/src/components/CompanyChip.tsx`
- Modify: `frontend/src/components/CompanyChip.test.tsx`
- Modify: `frontend/src/components/AlertCompanies.tsx:138`

**Interfaces:**
- Consumes: `ReasoningPanel`'s new `eventType` prop (Task 6)
- Produces: `CompanyChip` gains a second, optional prop: `eventType?: string | null`

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/CompanyChip.test.tsx`:

```tsx
it('passes eventType through to the expanded ReasoningPanel', async () => {
  const withEvidence = { ...company, reasons: ['x'], evidence_refs: [] };
  render(<CompanyChip company={withEvidence} eventType="crude_oil" />);
  await userEvent.click(screen.getByRole('button', { name: /reliance/i }));
  await userEvent.click(screen.getByRole('button', { name: 'Why this call' }));
  expect(screen.getByText('Event: Crude oil')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/CompanyChip.test.tsx`
Expected: FAIL — `CompanyChip` doesn't accept or forward an `eventType` prop
yet

- [ ] **Step 3: Update CompanyChip and its caller**

```tsx
// frontend/src/components/CompanyChip.tsx — replace the component signature and the ReasoningPanel render:
export default function CompanyChip({
  company,
  eventType,
}: {
  company: AlertCompany;
  eventType?: string | null;
}) {
  // ...unchanged body above...
  return (
    <div className="flex flex-col gap-2">
      {/* ...unchanged chip button... */}
      {expanded && <ReasoningPanel company={company} eventType={eventType} />}
    </div>
  );
}
```

(Only the function signature's destructured props and the final
`<ReasoningPanel .../>` line change — everything else in
`frontend/src/components/CompanyChip.tsx` stays exactly as it is today.)

```tsx
// frontend/src/components/AlertCompanies.tsx:138 — replace:
<CompanyChip company={company} />
// with:
<CompanyChip company={company} eventType={alert.event_type} />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/CompanyChip.test.tsx`
Expected: PASS (all tests, including every pre-existing one — none of them
pass `eventType`, so it's `undefined` and the new test-7 behavior is
additive)

- [ ] **Step 5: Run the full frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: all tests pass

- [ ] **Step 6: Typecheck one more time**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/CompanyChip.tsx frontend/src/components/CompanyChip.test.tsx frontend/src/components/AlertCompanies.tsx
git commit -m "feat: thread event_type from Alert through to ReasoningPanel in the feed"
```

---

## Explicitly out of scope for this plan

`CompanyPage.tsx`'s separate "Latest Signal" section (different component,
different `LatestAlertSignal` type — follow-up if wanted). Real
non-English translations for the 11 new i18n keys (currently English in
every language slot, disclosed in "Deviations" above — needs native-speaker
review as a separate pass). A dedicated visual evidence-graph explorer.
