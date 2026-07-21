# Impact Charts — Phase 6 (Mount Charts 1 & 4-8) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mount all 6 grouping charts (Impact Tree, Multi-Level Impact Tree/Cascade Levels, Confidence Tree, Positive/Negative Split, Timeline Tree, Sector Tree) on one page, with a fully consistent interaction model — every company click opens the same inline drawer, every chart shows the portfolio ring on held companies.

**Architecture:** 4 of the 6 charts (`ConfidenceTree`, `SplitTree`, `TimelineTree`, `SectorTree`) already ship fully self-contained (own `ChartCardShell` number, own `useCompanySelection`+`ReasoningPanel` wiring) — they only need mounting. The other 2 need real code changes first: `ImpactTree` currently has zero click-wiring (plain, non-interactive company cards), and `LevelTree` currently navigates to a separate page on click instead of using the shared inline-drawer pattern the other 5 already use — per explicit user decision, this plan makes `LevelTree` consistent with the other 5 rather than keeping it different. Two shared card components (`CompanyCard`, `CompanyRow`) get a portfolio-ring treatment, benefiting every chart across this phase AND Phase 7.

**Tech Stack:** React, TypeScript, Vitest, Testing Library.

## Global Constraints

- **User decision (explicit, this session):** all 6 charts use the SAME click-to-open-inline-drawer interaction (`useCompanySelection` + `ReasoningPanel`) — no chart navigates to a separate page. This reverses `LevelTree`'s current navigate-to-`AlertCompanyAnalysisPage` behavior.
- **User decision (explicit, this session):** add a portfolio-ring visual treatment to held companies (`in_my_holdings`) now, not deferred. Uses the app's EXISTING `accent-secondary` color token (`frontend/tailwind.config.ts`'s `'accent-secondary': 'rgb(var(--color-accent-secondary) / <alpha-value>)'`, already validated — teal in light mode, muted grey in dark mode) — no new hex, no palette-validator run needed.
- Chart numbering, once all 6 are mounted together, must be `1, 4, 5, 6, 7, 8` (2, 3, 9, 10 are reserved for Phase 7's graph charts). Verified current numbers already claimed: `ImpactTree`=1, `ConfidenceTree`=5, `SplitTree`=6, `TimelineTree`=7, `SectorTree`=8 (all correct already, no change needed). `LevelTree` currently claims `number={2}` — this plan changes it to `4`.
- Chart TITLES are NOT renamed to match the source task doc's own naming table (e.g. `ImpactTree`'s existing title "Multi-Level Impact Tree" stays as-is, `LevelTree`'s existing title "Cascade Levels" stays as-is) — these were deliberate, explicit, user-approved choices from earlier this session's mockup-selection work, and the doc's own chart-name column is a looser reference label, not a literal UI-copy mandate. Renaming them now based on an externally-authored doc would be unrequested scope creep.
- `CompanyCard`/`CompanyRow` are shared by every chart in this codebase (confirmed: `ImpactTree`, `LevelTree` use `CompanyCard`; `ConfidenceTree`, `SplitTree`, `TimelineTree`, `SectorTree` use `CompanyRow`) — Task 1's portfolio-ring change to these two files is the ONLY place this needs implementing; no per-chart duplication.
- Verified current code this plan is grounded against (read directly): `frontend/src/features/visualize/charts/{ImpactTree,LevelTree,ConfidenceTree,SplitTree,TimelineTree,SectorTree,ChartCardShell,cards/CompanyCard,cards/CompanyRow,useCompanySelection}.tsx`, `frontend/src/components/ReasoningPanel.tsx`, `frontend/src/pages/{AlertChartsPage,AlertCascadePage}.tsx`, `frontend/src/App.tsx`'s route table, `frontend/src/index.css`'s color tokens, `frontend/tailwind.config.ts`.

---

### Task 1: Portfolio-ring treatment on `CompanyCard`/`CompanyRow`

**Files:**
- Modify: `frontend/src/features/visualize/charts/cards/CompanyCard.tsx`
- Modify: `frontend/src/features/visualize/charts/cards/CompanyRow.tsx`
- Test: `frontend/src/features/visualize/charts/cards/CompanyCard.test.tsx` (create if it doesn't exist — check first)
- Test: `frontend/src/features/visualize/charts/cards/CompanyRow.test.tsx` (create if it doesn't exist — check first)

**Interfaces:**
- Produces: both components now render a `ring-2 ring-accent-secondary` visual treatment whenever `company.in_my_holdings` is `true` — reads the field directly off the `company` prop already passed in, no new prop added to either component's signature.

- [ ] **Step 1: Check for existing test files**

Run (from `frontend/`): `ls src/features/visualize/charts/cards/*.test.tsx 2>/dev/null` (or PowerShell `Get-ChildItem src/features/visualize/charts/cards/*.test.tsx -ErrorAction SilentlyContinue`). If `CompanyCard.test.tsx`/`CompanyRow.test.tsx` already exist, add the new tests below to them (matching their existing style/imports); if not, create them fresh using the pattern shown.

- [ ] **Step 2: Write the failing tests**

Add to (or create) `frontend/src/features/visualize/charts/cards/CompanyCard.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CompanyCard from './CompanyCard';
import type { AlertCompany } from '../../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention',
    confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('CompanyCard portfolio ring', () => {
  it('shows the portfolio ring when the company is held', () => {
    render(<CompanyCard company={company({ in_my_holdings: true })} />);
    expect(screen.getByText('AAA').closest('div')).toHaveClass('ring-2', 'ring-accent-secondary');
  });

  it('shows no ring when the company is not held', () => {
    render(<CompanyCard company={company({ in_my_holdings: false })} />);
    expect(screen.getByText('AAA').closest('div')).not.toHaveClass('ring-2');
  });
});
```

Add to (or create) `frontend/src/features/visualize/charts/cards/CompanyRow.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CompanyRow from './CompanyRow';
import type { AlertCompany } from '../../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention',
    confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('CompanyRow portfolio ring', () => {
  it('shows the portfolio ring when the company is held (non-interactive row)', () => {
    render(<CompanyRow company={company({ in_my_holdings: true })} />);
    expect(screen.getByText('AAA').closest('div')).toHaveClass('ring-2', 'ring-accent-secondary');
  });

  it('shows the portfolio ring when the company is held (interactive/clickable row)', () => {
    render(<CompanyRow company={company({ in_my_holdings: true })} onClick={() => {}} />);
    expect(screen.getByText('AAA').closest('button')).toHaveClass('ring-2', 'ring-accent-secondary');
  });

  it('shows no ring when the company is not held', () => {
    render(<CompanyRow company={company({ in_my_holdings: false })} />);
    expect(screen.getByText('AAA').closest('div')).not.toHaveClass('ring-2');
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/features/visualize/charts/cards/CompanyCard.test.tsx src/features/visualize/charts/cards/CompanyRow.test.tsx`
Expected: FAIL (no `ring-2`/`ring-accent-secondary` class present yet).

- [ ] **Step 4: Add the ring to `CompanyCard.tsx`**

In `frontend/src/features/visualize/charts/cards/CompanyCard.tsx`, change the `className` computation (currently):

```tsx
  const className = `flex flex-col gap-0.5 rounded-lg border p-2.5 text-left theme-light:shadow-neu-sm ${
    selected ? 'border-ink theme-light:border-ink' : 'border-hairline theme-light:border-transparent'
  }`;
```

to:

```tsx
  const className = `flex flex-col gap-0.5 rounded-lg border p-2.5 text-left theme-light:shadow-neu-sm ${
    selected ? 'border-ink theme-light:border-ink' : 'border-hairline theme-light:border-transparent'
  } ${company.in_my_holdings ? 'ring-2 ring-accent-secondary' : ''}`;
```

- [ ] **Step 5: Add the ring to `CompanyRow.tsx`**

In `frontend/src/features/visualize/charts/cards/CompanyRow.tsx`, change the two return statements (currently):

```tsx
  if (!onClick) {
    return <div className="flex w-full items-center gap-2 rounded-md px-2 py-1.5">{content}</div>;
  }

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-page ${
        selected ? 'bg-page ring-1 ring-inset ring-hairline' : ''
      }`}
    >
      {content}
    </button>
  );
```

to:

```tsx
  const ringClass = company.in_my_holdings ? 'ring-2 ring-accent-secondary' : '';

  if (!onClick) {
    return <div className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 ${ringClass}`}>{content}</div>;
  }

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-page ${
        selected ? 'bg-page' : ''
      } ${ringClass}`}
    >
      {content}
    </button>
  );
```

(The `selected` state's own visual treatment changes from `ring-1 ring-inset ring-hairline` to just `bg-page` — Tailwind's `ring-*` utilities share one underlying CSS custom property per element, so a `selected` ring and a portfolio ring cannot both render distinctly on the same element at once. `bg-page` alone still gives `selected` a clearly visible background shift, freeing the ring exclusively for the portfolio indicator so both states stay independently visible when they co-occur.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `npx vitest run src/features/visualize/charts/cards/CompanyCard.test.tsx src/features/visualize/charts/cards/CompanyRow.test.tsx`
Expected: PASS, all tests including the 5 new ones.

- [ ] **Step 7: Run the full frontend suite + typecheck**

Run (from `frontend/`): `npx vitest run` and `npx tsc --noEmit`
Expected: both PASS. `CompanyRow`'s existing `selected` tests (in whichever chart test files exercise it, e.g. `ConfidenceTree.test.tsx`) must still pass with the new `bg-page`-only selected styling — if any existing test asserts the OLD `ring-1`/`ring-hairline` classes specifically (rather than just checking `selected`/`aria-pressed` behavior), it needs a matching class-name update; check for this and fix any such test.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/visualize/charts/cards/CompanyCard.tsx frontend/src/features/visualize/charts/cards/CompanyRow.tsx frontend/src/features/visualize/charts/cards/CompanyCard.test.tsx frontend/src/features/visualize/charts/cards/CompanyRow.test.tsx
git commit -m "feat: add portfolio-ring treatment to CompanyCard/CompanyRow for held companies"
```

---

### Task 2: `ImpactTree` click-wiring + `LevelTree` rewrite (drop navigation, add inline drawer)

**Files:**
- Modify: `frontend/src/features/visualize/charts/ImpactTree.tsx`
- Modify: `frontend/src/features/visualize/charts/ImpactTree.test.tsx`
- Modify: `frontend/src/features/visualize/charts/LevelTree.tsx`
- Modify: `frontend/src/features/visualize/charts/LevelTree.test.tsx`
- Modify: `frontend/src/pages/AlertCascadePage.tsx` (its `LevelTree` call site loses the `alertId` prop this task removes — see Task 3, which actually deletes this whole page; this task alone would leave it broken, so Task 3 must land in the same PR/session as this one, not be deferred)

**Interfaces:**
- Consumes: `useCompanySelection` (existing, `./useCompanySelection`), `ReasoningPanel` (existing, `../../../components/ReasoningPanel`).
- Produces: `ImpactTree`'s props gain `eventType?: string | null`. `LevelTree`'s props change from `{ alertId: number; companies: AlertCompany[] }` to `{ companies: AlertCompany[]; eventType?: string | null }` (drops `alertId`, adds `eventType`) — a breaking signature change, every call site must be updated (Task 3 is the only other call site, `AlertCascadePage.tsx`, which Task 3 deletes entirely rather than updates).

- [ ] **Step 1: Write the failing `ImpactTree` tests**

Add to `frontend/src/features/visualize/charts/ImpactTree.test.tsx` (add `MemoryRouter`/`LanguageProvider` wrapping — check the file's current top-level `render` helper; if it's a bare `render` from `@testing-library/react` with no providers, add a local wrapper matching `ConfidenceTree.test.tsx`'s pattern: `MemoryRouter` + `LanguageProvider`, since `ReasoningPanel` needs `useLanguage` and links inside it use `react-router-dom`):

```tsx
it('expands a ReasoningPanel when a direct company is tapped', async () => {
  const { default: userEvent } = await import('@testing-library/user-event');
  render(
    <ImpactTree
      companies={[company({ company_id: 1, ticker: 'HDFCBANK', sector: 'banking', impact_level: 'direct', rationale: 'Lower rates lift loan demand.' })]}
      article={article}
      alertCreatedAt="2026-07-17T10:30:00Z"
    />,
  );
  await userEvent.click(screen.getByText('HDFCBANK'));
  expect(screen.getByText(/Lower rates lift loan demand/)).toBeInTheDocument();
});

it('expands a ReasoningPanel when an indirect (sub-sector) company is tapped', async () => {
  const { default: userEvent } = await import('@testing-library/user-event');
  render(
    <ImpactTree
      companies={[company({
        company_id: 1, ticker: 'ULTRACEMCO', sector: 'infra', impact_level: 'indirect_l1',
        parent_company_id: 99, rationale: 'Cement demand rises with construction activity.',
      })]}
      article={article}
      alertCreatedAt="2026-07-17T10:30:00Z"
    />,
  );
  await userEvent.click(screen.getByText('ULTRACEMCO'));
  expect(screen.getByText(/Cement demand rises/)).toBeInTheDocument();
});
```

(Adapt the exact `render`/`company`/`article` helper calls to match this file's ALREADY-established factory functions, shown earlier in the same file — don't redefine them.)

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/features/visualize/charts/ImpactTree.test.tsx`
Expected: FAIL (clicking a company does nothing today, no `ReasoningPanel` content appears).

- [ ] **Step 3: Wire click-to-drawer into `ImpactTree.tsx`**

In `frontend/src/features/visualize/charts/ImpactTree.tsx`, add to the imports (currently ending `import CompanyCard from './cards/CompanyCard';`):

```tsx
import ReasoningPanel from '../../../components/ReasoningPanel';
import { useCompanySelection } from './useCompanySelection';
```

Change `SectorBlock` (currently `function SectorBlock({ sector }: { sector: CompanyGroup }) {`) to:

```tsx
function SectorBlock({
  sector, selectedId, onToggle,
}: {
  sector: CompanyGroup; selectedId: number | null; onToggle: (id: number) => void;
}) {
  return (
    <div className="flex w-full flex-col items-center gap-3">
      <LevelHeader level="Level 1 · Direct Impact" name={sector.label} count={sector.companies.length} color={sector.color} />
      <WhyExplanation companies={sector.companies} />
      <Connector />
      <p className="font-data text-[10px] uppercase tracking-widest text-muted">Level 2 · Companies</p>
      <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {sector.companies.map((c) => (
          <CompanyCard key={c.company_id} company={c} onClick={() => onToggle(c.company_id)} selected={selectedId === c.company_id} />
        ))}
      </div>
    </div>
  );
}
```

Change `SubSectorBlock` (currently `function SubSectorBlock({ subSector }: { subSector: SubSectorGroup }) {`) to:

```tsx
function SubSectorBlock({
  subSector, selectedId, onToggle,
}: {
  subSector: SubSectorGroup; selectedId: number | null; onToggle: (id: number) => void;
}) {
  return (
    <div className="flex w-full flex-col items-center gap-3">
      <LevelHeader level="Level 3 · Indirect Ripple" name={subSector.label} count={subSector.companies.length} />
      <WhyExplanation companies={subSector.companies} />
      <Connector />
      <p className="font-data text-[10px] uppercase tracking-widest text-muted">Level 4 · Companies</p>
      <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {subSector.companies.map((c) => (
          <CompanyCard key={c.company_id} company={c} onClick={() => onToggle(c.company_id)} selected={selectedId === c.company_id} />
        ))}
      </div>
    </div>
  );
}
```

Change the default export's signature (currently `companies, article, alertCreatedAt,` destructured with matching type) to:

```tsx
export default function ImpactTree({
  companies,
  article,
  alertCreatedAt,
  eventType,
}: {
  companies: AlertCompany[];
  article: AlertArticle;
  alertCreatedAt: string;
  eventType?: string | null;
}) {
  const direct = companies.filter((c) => impactLevelKey(c) === 'direct');
  const sectorGroups = groupBySector(direct);
  const subSectorGroups = groupIndirectBySubSector(companies);
  const { toggle, selected, selectedId } = useCompanySelection(companies);
```

Change the two `.map()` call sites inside the JSX (currently `<SectorBlock key={sector.key} sector={sector} />` and `<SubSectorBlock key={subSector.key} subSector={subSector} />`) to pass the new props:

```tsx
              <SectorBlock key={sector.key} sector={sector} selectedId={selectedId} onToggle={toggle} />
```
```tsx
              <SubSectorBlock key={subSector.key} subSector={subSector} selectedId={selectedId} onToggle={toggle} />
```

Add the drawer render right before the closing `</ChartCardShell>` (i.e. as the last child inside the outer `<div className="flex flex-col items-center gap-4 p-4">`):

```tsx
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
```

- [ ] **Step 4: Run `ImpactTree` tests to verify they pass**

Run: `npx vitest run src/features/visualize/charts/ImpactTree.test.tsx`
Expected: PASS, all tests including the 2 new ones and every pre-existing test in this file (pre-existing tests never asserted "no click behavior," so they should be unaffected — if any pre-existing test's snapshot/query breaks because `CompanyCard` is now a `<button>` instead of a `<div>`, fix that test's query, don't weaken the new behavior).

- [ ] **Step 5: Write the failing `LevelTree` tests**

Replace `frontend/src/features/visualize/charts/LevelTree.test.tsx` entirely:

```tsx
import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import LevelTree from './LevelTree';
import type { AlertCompany } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

function render(companies: AlertCompany[], eventType?: string | null) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>
        <LevelTree companies={companies} eventType={eventType} />
      </LanguageProvider>
    </MemoryRouter>,
  );
}

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50', sector: 'it',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', confidence_score: 50,
    time_horizon: 'Short-Term', market: 'IN', in_my_holdings: false, past_mentions: [],
    impact_level: 'direct', parent_company_id: null,
    ...overrides,
  };
}

describe('LevelTree', () => {
  it('renders nothing for an empty company list', () => {
    const { container } = render([]);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders only a Direct Impact branch when every company is direct', () => {
    render([company({ company_id: 1, ticker: 'NVDA' })]);
    expect(screen.getAllByText('Direct Impact')).toHaveLength(2);
    expect(screen.getAllByText('Indirect Impact — Level 1')).toHaveLength(1);
    expect(screen.getByText('NVDA')).toBeInTheDocument();
  });

  it('shows every company flat within its level, with no parent-company grouping label', () => {
    render([
      company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct' }),
      company({ company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1 }),
      company({ company_id: 3, ticker: 'QCOM', name: 'Qualcomm', impact_level: 'indirect_l1', parent_company_id: 1 }),
    ]);
    expect(screen.getAllByText('Indirect Impact — Level 1')).toHaveLength(2);
    expect(screen.getByText('TSM')).toBeInTheDocument();
    expect(screen.getByText('QCOM')).toBeInTheDocument();
    expect(screen.queryByText(/via/i)).not.toBeInTheDocument();
  });

  it('shows indirect_l2 companies under their own level, flat like every other level', () => {
    render([
      company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct' }),
      company({ company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1 }),
      company({ company_id: 3, ticker: 'ASML.NS', name: 'ASML Holding', impact_level: 'indirect_l2', parent_company_id: 2 }),
    ]);
    expect(screen.getAllByText('Indirect Impact — Level 2')).toHaveLength(2);
    expect(screen.getByText('ASML.NS')).toBeInTheDocument();
  });

  it('renders wrapped in ChartCardShell with the Cascade Levels title and number 4', () => {
    render([company({ company_id: 1, ticker: 'NVDA' })]);
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('Cascade Levels')).toBeInTheDocument();
  });

  it('shows no full rationale text anywhere until a company is tapped', () => {
    render([
      company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct', rationale: 'Full paragraph rationale text.' }),
      company({
        company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1,
        rationale: 'Full paragraph rationale text.',
      }),
    ]);
    expect(screen.queryByText('Full paragraph rationale text.')).not.toBeInTheDocument();
  });

  it('expands a ReasoningPanel for a direct company on click', async () => {
    render([company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct', rationale: 'Chip demand accelerates.' })]);
    await userEvent.click(screen.getByText('NVDA'));
    expect(screen.getByText(/Chip demand accelerates/)).toBeInTheDocument();
  });

  it('expands a ReasoningPanel for a cascade company on click, using its own company id', async () => {
    render([
      company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct' }),
      company({
        company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1,
        rationale: 'Foundry capacity is the binding constraint.',
      }),
    ]);
    await userEvent.click(screen.getByText('TSM'));
    expect(screen.getByText(/Foundry capacity is the binding constraint/)).toBeInTheDocument();
  });

  it('shows a sector chip on every company card, including cascade companies', () => {
    render([
      company({ company_id: 1, ticker: 'NVDA', sector: 'it', impact_level: 'direct' }),
      company({ company_id: 2, ticker: 'TSM', name: 'TSMC', sector: 'metals', impact_level: 'indirect_l1', parent_company_id: 1 }),
    ]);
    expect(screen.getAllByText('IT').length).toBeGreaterThan(0);
    expect(screen.getByText('Metals')).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `npx vitest run src/features/visualize/charts/LevelTree.test.tsx`
Expected: FAIL — `LevelTree` doesn't accept this prop shape yet, still requires `alertId` and navigates instead of expanding a panel.

- [ ] **Step 7: Rewrite `LevelTree.tsx`**

Replace `frontend/src/features/visualize/charts/LevelTree.tsx` entirely:

```tsx
import { useMemo } from 'react';
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { IMPACT_LEVEL_ORDER, impactLevelColor, impactLevelKey, impactLevelLabel } from '../impactLevels';
import ChartCardShell from './ChartCardShell';
import CompanyCard from './cards/CompanyCard';
import { useCompanySelection } from './useCompanySelection';

function LevelConnector() {
  return (
    <div aria-hidden="true" className="flex justify-center py-0.5">
      <span className="text-muted">↓</span>
    </div>
  );
}

const LEGEND = [
  { label: impactLevelLabel('direct'), color: impactLevelColor('direct') },
  { label: impactLevelLabel('indirect_l1'), color: impactLevelColor('indirect_l1') },
  { label: impactLevelLabel('indirect_l2'), color: impactLevelColor('indirect_l2') },
];

export default function LevelTree({
  companies,
  eventType,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);

  const levels = useMemo(
    () =>
      IMPACT_LEVEL_ORDER.map((level) => ({
        level,
        companies: companies.filter((c) => impactLevelKey(c) === level),
      })).filter((l) => l.companies.length > 0),
    [companies],
  );

  if (levels.length === 0) return null;

  return (
    <ChartCardShell
      number={4}
      title="Cascade Levels"
      description="Companies affected at each cascade level -- direct, and the ripple effects it triggers"
      legend={LEGEND}
    >
      <div className="flex flex-col p-4">
        {levels.map(({ level, companies: levelCompanies }, i) => {
          const color = impactLevelColor(level);
          return (
            <div key={level} className="flex flex-col">
              {i > 0 && <LevelConnector />}
              <div className="mb-2 flex items-center gap-2">
                <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
                <p className="text-xs uppercase tracking-widest text-ink">{impactLevelLabel(level)}</p>
                <p className="text-xs text-muted">({levelCompanies.length})</p>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {levelCompanies.map((c) => (
                  <CompanyCard
                    key={c.company_id}
                    company={c}
                    showSector
                    onClick={() => toggle(c.company_id)}
                    selected={selectedId === c.company_id}
                  />
                ))}
              </div>
            </div>
          );
        })}
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
```

- [ ] **Step 8: Run `LevelTree` tests to verify they pass**

Run: `npx vitest run src/features/visualize/charts/LevelTree.test.tsx`
Expected: PASS, all 9 tests.

- [ ] **Step 9: Do NOT run the full suite yet**

`AlertCascadePage.tsx` (which still calls `LevelTree` with the now-removed `alertId` prop) will fail to typecheck/build until Task 3 updates it. Task 3 must be implemented in the same sitting as this task, before running `npx tsc --noEmit`/the full suite/committing anything that would leave the repo in a broken intermediate state on `master`. If Task 3 cannot immediately follow (e.g. this is being executed as two separate subagent dispatches), STOP after this step and hand off with an explicit note rather than committing broken code to `master`.

---

### Task 3: Mount all 6 charts on `AlertChartsPage`, remove the now-redundant `AlertCascadePage`

**Files:**
- Modify: `frontend/src/pages/AlertChartsPage.tsx`
- Modify: `frontend/src/pages/AlertChartsPage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Delete: `frontend/src/pages/AlertCascadePage.tsx`
- Delete: `frontend/src/pages/AlertCascadePage.test.tsx`

**Interfaces:**
- Consumes: `LevelTree({ companies, eventType })` (Task 2's new signature), `ConfidenceTree`/`SplitTree`/`TimelineTree`/`SectorTree({ companies, eventType })` (unchanged, already this shape), `ImpactTree({ companies, article, alertCreatedAt, eventType })` (Task 2's addition).

- [ ] **Step 1: Write the failing `AlertChartsPage` tests**

`frontend/src/pages/AlertChartsPage.test.tsx` already has an `alert(overrides: Partial<Alert> = {})` factory and a `renderPage(id = '1')` helper (wraps `AlertChartsPage` in `LanguageProvider` + `AuthProvider` + `MemoryRouter` at route `/alerts/:id/charts`), and mocks the fetch via `vi.spyOn(api, 'getAlert').mockResolvedValue(...)`. Use both directly — do not redefine them.

Remove the existing test `'links to the dedicated Cascade Levels page instead of rendering it inline'` (lines 87-94) — it asserts the exact link/behavior this plan removes. Remove the commented-out dead fixtures (`directCompany`/`inferredCompany`/`indirectCompany`, lines 36-55) and the commented-out dead test block referenced afterward (`// it('shows the pager labels for all six chart types'...` and anything else under a `// --- Chart system disabled ---` marker in this file) — all superseded by this task's real test below.

Add:

```tsx
it('renders all six grouping charts for an alert with mixed direct/indirect, bullish/bearish, multi-sector companies', async () => {
  vi.spyOn(api, 'getAlert').mockResolvedValue(alert({
    event_type: 'crude_oil',
    companies: [
      {
        company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance Industries', index_tier: 'NIFTY50',
        sector: 'oil_gas', direction: 'bullish', magnitude_low: 2, magnitude_high: 4,
        rationale: 'Refiner margins widen.', key_points: ['Crude eases'], confidence_score: 80,
        time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
        in_my_holdings: false, past_mentions: [], impact_level: 'direct', parent_company_id: null,
      },
      {
        company_id: 2, ticker: 'INDIGO.NS', name: 'InterGlobe Aviation', index_tier: 'NIFTY50',
        sector: 'railways_transport', direction: 'bearish', magnitude_low: 1, magnitude_high: 3,
        rationale: 'Fuel costs rise.', key_points: ['ATF costs up'], confidence_score: 55,
        time_horizon: 'Medium-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
        in_my_holdings: true, past_mentions: [], impact_level: 'indirect_l1', parent_company_id: 1,
      },
    ],
  }));
  renderPage('1');

  expect(await screen.findByText('Multi-Level Impact Tree')).toBeInTheDocument();
  expect(screen.getByText('Cascade Levels')).toBeInTheDocument();
  expect(screen.getByText('Confidence Tree')).toBeInTheDocument();
  expect(screen.getByText('Positive / Negative Split')).toBeInTheDocument();
  expect(screen.getByText('Timeline Tree')).toBeInTheDocument();
  expect(screen.getByText('Sector Tree')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/pages/AlertChartsPage.test.tsx`
Expected: FAIL (only `ImpactTree` renders today).

- [ ] **Step 3: Rewrite `AlertChartsPage.tsx`**

Replace the whole file's import block (currently lines 1-35, including the large `--- Chart system disabled ---` comment block and the dead `CHARTS` array) with:

```tsx
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getAlert, type Alert, type AlertCompany } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
import { computeNetSignal } from '../features/visualize/transforms';
import { impactLevelKey } from '../features/visualize/impactLevels';
import ImpactTree from '../features/visualize/charts/ImpactTree';
import LevelTree from '../features/visualize/charts/LevelTree';
import ConfidenceTree from '../features/visualize/charts/ConfidenceTree';
import SplitTree from '../features/visualize/charts/SplitTree';
import TimelineTree from '../features/visualize/charts/TimelineTree';
import SectorTree from '../features/visualize/charts/SectorTree';
```

Remove the second disabled block (currently lines 87-145, the commented-out `DirectlyAffectedSectors`/`ImpactSummaryBanner` functions) entirely — dead code from an earlier, fully superseded card system, no longer referenced anywhere.

Remove the third disabled block inside the component body (currently lines 156-172, the commented-out `index`/`forceCollapse`/`collapseVersion` state and `expandAll`/`collapseAll` functions) entirely.

Remove the fourth disabled block (currently lines 189-194, the commented-out `swipeHandlers`).

Remove the fifth disabled block (currently lines 196-198, the commented-out `useCompanySelection` line — each chart now manages its own selection internally, nothing needed at the page level).

Remove the sixth disabled block (currently lines 207-209, the commented-out `const { Component } = CHARTS[index];`).

Change the final `return` statement's chart-rendering section (currently):

```tsx
      <StatBar companies={alert.companies} breadth={breadth} />
      <div className="flex-1 overflow-y-auto">
        <ImpactTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} />
        <div className="flex justify-center border-t border-hairline p-4">
          <Link
            to={`/alerts/${alert.id}/charts/cascade`}
            className="rounded-lg border border-hairline px-4 py-2 text-xs uppercase tracking-widest text-ink hover:bg-surface"
          >
            View Cascade Levels →
          </Link>
        </div>
      </div>
```

to:

```tsx
      <StatBar companies={alert.companies} breadth={breadth} />
      <div className="flex-1 overflow-y-auto">
        <ImpactTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} />
        <div className="border-t border-hairline">
          <LevelTree companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <ConfidenceTree companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <SplitTree companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <TimelineTree companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <SectorTree companies={alert.companies} eventType={alert.event_type} />
        </div>
      </div>
```

Remove the now-unused `Link` import (the only usage was the removed "View Cascade Levels →" link) — check the top-of-file `import { Link, useNavigate, useParams } from 'react-router-dom';` and change it to `import { useNavigate, useParams } from 'react-router-dom';` if `Link` is no longer referenced anywhere else in the file (grep the file first to confirm before removing the import).

- [ ] **Step 4: Delete `AlertCascadePage` (now fully redundant)**

`AlertCascadePage.tsx`'s sole purpose was showing `LevelTree` on its own page, reached via the "View Cascade Levels →" link this task just removed. `LevelTree` is now mounted directly and identically on `AlertChartsPage` (Task 2 made it render the same content, same interaction model, regardless of where it's mounted) — keeping a separate page that shows the exact same chart is dead weight, not a distinct feature.

Delete `frontend/src/pages/AlertCascadePage.tsx` and `frontend/src/pages/AlertCascadePage.test.tsx`.

In `frontend/src/App.tsx`, remove the import line `import AlertCascadePage from './pages/AlertCascadePage';` and the route `<Route path="/alerts/:id/charts/cascade" element={<AlertCascadePage />} />`.

- [ ] **Step 5: Run tests to verify they pass**

Run (from `frontend/`): `npx vitest run src/pages/AlertChartsPage.test.tsx`
Expected: PASS, including the new all-six-charts test and every remaining pre-existing test in this file (the two `getAlert`-success/-failure tests from before this task).

- [ ] **Step 6: Run the full frontend suite + typecheck + build**

Run (from `frontend/`): `npx vitest run`, `npx tsc --noEmit`, `npm run build`
Expected: all three PASS, no regressions, no stale references to `AlertCascadePage` or the deleted route anywhere (grep the whole `frontend/src` tree for `AlertCascadePage`/`charts/cascade` to confirm zero remaining references before considering this done).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/AlertChartsPage.tsx frontend/src/pages/AlertChartsPage.test.tsx frontend/src/App.tsx
git rm frontend/src/pages/AlertCascadePage.tsx frontend/src/pages/AlertCascadePage.test.tsx
git commit -m "feat: mount all six grouping charts on AlertChartsPage, remove redundant AlertCascadePage"
```

---

## Explicitly out of scope (this plan)

Charts 2/3/9/10 (Phase 7 — the graph charts, need `@xyflow/react`). Any visual/aesthetic redesign beyond what's already shipped for each of the 6 charts (this plan only adds click-wiring, portfolio ring, and mounting — no new layout work). Renaming any chart's title/description to match the source task doc's own naming table (deliberately left as-is, see Global Constraints). A dedicated `CompanyCard`/`CompanyRow` visual regression check in a real browser, light AND dark mode — recommended as a manual follow-up per this project's own established convention (documented, not performed automatically by an agentic worker without browser access).

## Definition of done (this plan only)

1. All 6 grouping charts render on `AlertChartsPage`, numbered `1, 4, 5, 6, 7, 8` with no gaps/collisions.
2. Every company card across all 6 charts is clickable and opens the same inline `ReasoningPanel` drawer — no navigation to a separate page anywhere.
3. A held company (`in_my_holdings: true`) shows a visible ring on its card/row in every chart (both `CompanyCard` and `CompanyRow` consumers).
4. `AlertCascadePage` and its route are fully removed, with zero remaining references anywhere in the frontend.
5. Full frontend test suite green, `tsc --noEmit` clean, `npm run build` succeeds.
