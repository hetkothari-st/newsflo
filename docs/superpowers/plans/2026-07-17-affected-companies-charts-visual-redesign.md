# Affected-Companies Charts Visual Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `AlertChartsPage`'s Normal/Drilldown container layout and restyle 5 of its 7 existing chart components into a shared numbered-card visual shell, matching the reference mockups, using only data that already exists.

**Architecture:** A new `ChartCardShell` wrapper (numbered badge, title, description, legend) is adopted by `LevelTree`, `ConfidenceTree`, `SplitTree`, `TimelineTree`, `SectorTree`. `ImpactCard` gains a controlled collapse mode and a "View Details" affordance, reused both inside those charts and in two new page-level sections on `AlertChartsPage`: a "Directly Affected Sectors" card grid (Normal View) and a pinned `LevelTree` overview with Expand All/Collapse All (Drilldown View), each followed by an Impact Summary banner.

**Tech Stack:** React 18 + TypeScript, Tailwind (CSS-variable theme tokens), Vitest + React Testing Library (existing test setup at `frontend/src/test/setup.ts`), no new dependencies.

## Global Constraints

- No new npm dependencies (no chart/graph library — everything hand-rolled HTML/CSS/SVG per existing codebase convention).
- No backend changes in this plan — every task uses `AlertCompany`/`Alert` fields that already exist.
- `TierRows.tsx` and `ImpactBar.tsx` are **out of scope** — left exactly as-is (see the design spec's "Correction" section for why: neither maps cleanly onto the mockup's 10-chart taxonomy; their fate is decided in the follow-up plan).
- Preserve every existing exported prop name/shape unless a task explicitly changes it — other call sites (tests, `AlertChartsPage`) must keep compiling.
- Every new/changed component gets a colocated `.test.tsx` using the existing pattern (`@testing-library/react`, see any current `*.test.tsx` in `frontend/src/features/visualize/charts/` for the harness style already in use).

---

### Task 1: `ImpactCard` — controlled collapse + "View Details"

**Files:**
- Modify: `frontend/src/features/visualize/charts/cards/ImpactCard.tsx`
- Test: `frontend/src/features/visualize/charts/cards/ImpactCard.test.tsx` (new)

**Interfaces:**
- Produces: `ImpactCard` gains three new optional props — `collapsed?: boolean`, `onToggle?: () => void`, `onViewDetails?: () => void`. When `collapsed` is provided, the card is **controlled** (its internal `useState` is ignored, `onToggle` fires on header click instead of flipping local state). When omitted, behavior is byte-identical to today (uncontrolled, `defaultCollapsed` still works). `onViewDetails`, when provided, renders a "View Details →" button under the children whenever the card is expanded.
- Consumes: nothing new (`NetSignal`, `severityLabel` from `../../transforms`, unchanged).

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/visualize/charts/cards/ImpactCard.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ImpactCard from './ImpactCard';
import type { NetSignal } from '../../transforms';

const SIGNAL: NetSignal = { direction: 'bullish', bullishCount: 1, bearishCount: 0, avgConfidence: 80 };

describe('ImpactCard', () => {
  it('is uncontrolled by default: clicking the header toggles its own collapsed state', () => {
    render(
      <ImpactCard label="Banking" color="#4A90D9" signal={SIGNAL} companyCount={1}>
        <p>child content</p>
      </ImpactCard>,
    );
    expect(screen.getByText('child content')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /banking/i }));
    expect(screen.queryByText('child content')).not.toBeInTheDocument();
  });

  it('is controlled when collapsed is provided: header click calls onToggle instead of flipping local state', () => {
    const onToggle = vi.fn();
    const { rerender } = render(
      <ImpactCard label="Banking" color="#4A90D9" signal={SIGNAL} companyCount={1} collapsed={false} onToggle={onToggle}>
        <p>child content</p>
      </ImpactCard>,
    );
    fireEvent.click(screen.getByRole('button', { name: /banking/i }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    // parent hasn't re-rendered with collapsed=true yet -- content is still visible,
    // proving the click did NOT flip any internal state on its own.
    expect(screen.getByText('child content')).toBeInTheDocument();
    rerender(
      <ImpactCard label="Banking" color="#4A90D9" signal={SIGNAL} companyCount={1} collapsed={true} onToggle={onToggle}>
        <p>child content</p>
      </ImpactCard>,
    );
    expect(screen.queryByText('child content')).not.toBeInTheDocument();
  });

  it('renders a View Details button when onViewDetails is provided, and calls it on click', () => {
    const onViewDetails = vi.fn();
    render(
      <ImpactCard label="Banking" color="#4A90D9" signal={SIGNAL} companyCount={1} onViewDetails={onViewDetails}>
        <p>child content</p>
      </ImpactCard>,
    );
    fireEvent.click(screen.getByRole('button', { name: /view details/i }));
    expect(onViewDetails).toHaveBeenCalledTimes(1);
  });

  it('omits the View Details button when onViewDetails is not provided', () => {
    render(
      <ImpactCard label="Banking" color="#4A90D9" signal={SIGNAL} companyCount={1}>
        <p>child content</p>
      </ImpactCard>,
    );
    expect(screen.queryByRole('button', { name: /view details/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/features/visualize/charts/cards/ImpactCard.test.tsx`
Expected: FAIL — `collapsed`/`onToggle`/`onViewDetails` props don't exist yet, "View Details" text never renders.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/visualize/charts/cards/ImpactCard.tsx
import { useState, type ReactNode } from 'react';
import type { NetSignal } from '../../transforms';
import { severityLabel } from '../../transforms';

function tintHex(hex: string, alphaHex: string): string | undefined {
  return hex.startsWith('#') && hex.length === 7 ? `${hex}${alphaHex}` : undefined;
}

export default function ImpactCard({
  label,
  color,
  signal,
  companyCount,
  defaultCollapsed = false,
  collapsed: collapsedProp,
  onToggle,
  onViewDetails,
  children,
}: {
  label: string;
  color: string;
  signal: NetSignal;
  companyCount: number;
  defaultCollapsed?: boolean;
  collapsed?: boolean;
  onToggle?: () => void;
  onViewDetails?: () => void;
  children: ReactNode;
}) {
  const [internalCollapsed, setInternalCollapsed] = useState(defaultCollapsed);
  const isControlled = collapsedProp !== undefined;
  const collapsed = isControlled ? collapsedProp : internalCollapsed;
  const handleHeaderClick = () => {
    if (isControlled) onToggle?.();
    else setInternalCollapsed((v) => !v);
  };

  const badgeTone = signal.direction === 'even' ? 'text-muted' : signal.direction === 'bullish' ? 'text-bullish' : 'text-bearish';
  const badgeBg = signal.direction === 'even' ? undefined : tintHex(signal.direction === 'bullish' ? '#3E9B5C' : '#E85D4C', '1F');

  return (
    <div
      className="flex min-w-0 flex-col gap-2.5 rounded-xl border border-hairline p-3.5 theme-light:border-transparent theme-light:shadow-neu-sm"
      style={{ backgroundColor: tintHex(color, '0D') ?? 'rgb(var(--color-surface))' }}
    >
      <button type="button" onClick={handleHeaderClick} aria-expanded={!collapsed} className="flex items-start gap-2.5 text-left">
        <span aria-hidden="true" className="mt-0.5 h-8 w-8 shrink-0 rounded-lg" style={{ backgroundColor: color }} />
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-ink">{label}</span>
            <span aria-hidden="true" className="ml-auto shrink-0 text-[10px] text-muted">
              {collapsed ? '▸' : '▾'}
            </span>
          </span>
          <span className="flex items-center gap-2 text-xs">
            <span className={`shrink-0 rounded-full px-2 py-0.5 font-medium uppercase tracking-wide ${badgeTone}`} style={{ backgroundColor: badgeBg }}>
              {severityLabel(signal)}
            </span>
            <span className="truncate text-muted">
              {companyCount} {companyCount === 1 ? 'company' : 'companies'} · avg {signal.avgConfidence}% confidence
            </span>
          </span>
        </span>
      </button>
      {!collapsed && (
        <div className="flex flex-col gap-1">
          {children}
          {onViewDetails && (
            <button type="button" onClick={onViewDetails} className="mt-1 self-end text-xs text-muted hover:text-ink">
              View Details →
            </button>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/features/visualize/charts/cards/ImpactCard.test.tsx`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full existing chart test suite to confirm no regression**

Run: `cd frontend && npx vitest run src/features/visualize/charts`
Expected: PASS — `SectorTree`/`LevelTree`/`ConfidenceTree` etc. all still use `ImpactCard` with only the props they already pass (`collapsed`/`onToggle`/`onViewDetails` all optional), so none of them should break.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/visualize/charts/cards/ImpactCard.tsx frontend/src/features/visualize/charts/cards/ImpactCard.test.tsx
git commit -m "feat: add controlled collapse and View Details to ImpactCard"
```

---

### Task 2: `ChartCardShell` — shared numbered-card wrapper

**Files:**
- Create: `frontend/src/features/visualize/charts/ChartCardShell.tsx`
- Test: `frontend/src/features/visualize/charts/ChartCardShell.test.tsx`

**Interfaces:**
- Produces:
  ```ts
  export interface ChartLegendItem {
    label: string;
    color: string;
  }

  export default function ChartCardShell(props: {
    number: number;
    title: string;
    description: string;
    legend?: ChartLegendItem[];
    children: ReactNode;
  }): JSX.Element
  ```
- Consumes: nothing (pure presentational wrapper).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/visualize/charts/ChartCardShell.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ChartCardShell from './ChartCardShell';

describe('ChartCardShell', () => {
  it('renders the numbered badge, title, description, and children', () => {
    render(
      <ChartCardShell number={5} title="Confidence Tree" description="Tree showing companies with confidence scores">
        <p>chart body</p>
      </ChartCardShell>,
    );
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('Confidence Tree')).toBeInTheDocument();
    expect(screen.getByText('Tree showing companies with confidence scores')).toBeInTheDocument();
    expect(screen.getByText('chart body')).toBeInTheDocument();
  });

  it('renders legend items when provided', () => {
    render(
      <ChartCardShell number={5} title="Confidence Tree" description="desc" legend={[{ label: 'High Confidence', color: '#25508F' }]}>
        <p>body</p>
      </ChartCardShell>,
    );
    expect(screen.getByText('High Confidence')).toBeInTheDocument();
  });

  it('omits the legend row entirely when legend is not provided', () => {
    const { container } = render(
      <ChartCardShell number={5} title="Confidence Tree" description="desc">
        <p>body</p>
      </ChartCardShell>,
    );
    expect(container.querySelector('[data-testid="chart-legend"]')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/ChartCardShell.test.tsx`
Expected: FAIL — module doesn't exist yet.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/visualize/charts/ChartCardShell.tsx
import type { ReactNode } from 'react';

export interface ChartLegendItem {
  label: string;
  color: string;
}

export default function ChartCardShell({
  number,
  title,
  description,
  legend,
  children,
}: {
  number: number;
  title: string;
  description: string;
  legend?: ChartLegendItem[];
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-3 px-4 pt-4">
        <span
          aria-hidden="true"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-hairline text-[11px] text-muted"
        >
          {number}
        </span>
        <div className="flex flex-col gap-0.5">
          <p className="text-sm font-medium text-ink">{title}</p>
          <p className="text-xs text-muted">{description}</p>
        </div>
      </div>
      {children}
      {legend && legend.length > 0 && (
        <div data-testid="chart-legend" className="flex flex-wrap gap-3 border-t border-hairline px-4 py-3 text-[11px] text-muted">
          {legend.map((item) => (
            <span key={item.label} className="inline-flex items-center gap-1.5">
              <span aria-hidden="true" className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
              {item.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/ChartCardShell.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/ChartCardShell.tsx frontend/src/features/visualize/charts/ChartCardShell.test.tsx
git commit -m "feat: add ChartCardShell numbered-card wrapper"
```

---

### Task 3: `LevelTree` — wrap in `ChartCardShell` (#1 Impact Tree) + controlled collapse-all

**Files:**
- Modify: `frontend/src/features/visualize/charts/LevelTree.tsx`
- Test: `frontend/src/features/visualize/charts/LevelTree.test.tsx` (new — none exists today)

**Interfaces:**
- Produces: `LevelTree` gains an exported `ForceCollapseSignal` type and an optional `forceCollapse?: ForceCollapseSignal` prop. Bumping `forceCollapse.version` with `mode: 'collapse'` collapses every `ImpactCard` on the tree; `mode: 'expand'` expands all of them. Existing `companies`/`eventType` props unchanged.
- Consumes: `ChartCardShell` (Task 2), `ImpactCard`'s new `collapsed`/`onToggle` props (Task 1), `IMPACT_LEVEL_COLOR`/`impactLevelLabel`/`impactLevelColor` from `../impactLevels` (unchanged), `groupBySector`/`computeNetSignal` from `../transforms` (unchanged).

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/visualize/charts/LevelTree.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import LevelTree from './LevelTree';
import type { AlertCompany } from '../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'TEST', name: 'Test Co', index_tier: 'NIFTY50', direction: 'bullish',
    magnitude_low: 1, magnitude_high: 2, rationale: 'r', key_points: [], confidence_score: 80,
    time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [], sector: 'banking', impact_level: 'direct',
    ...overrides,
  };
}

describe('LevelTree', () => {
  const companies = [
    company({ company_id: 1, ticker: 'HDFC', sector: 'banking', impact_level: 'direct' }),
    company({ company_id: 2, ticker: 'BAJFIN', sector: 'banking', impact_level: 'indirect_l1', parent_company_id: 1 }),
  ];

  it('renders wrapped in ChartCardShell with the Impact Tree title and number 1', () => {
    render(<LevelTree companies={companies} />);
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('Impact Tree')).toBeInTheDocument();
  });

  it('forceCollapse with mode collapse hides every card, mode expand shows them again', () => {
    const { rerender } = render(<LevelTree companies={companies} />);
    expect(screen.getByText('HDFC')).toBeInTheDocument();

    rerender(<LevelTree companies={companies} forceCollapse={{ mode: 'collapse', version: 1 }} />);
    expect(screen.queryByText('HDFC')).not.toBeInTheDocument();
    expect(screen.queryByText('BAJFIN')).not.toBeInTheDocument();

    rerender(<LevelTree companies={companies} forceCollapse={{ mode: 'expand', version: 2 }} />);
    expect(screen.getByText('HDFC')).toBeInTheDocument();
    expect(screen.getByText('BAJFIN')).toBeInTheDocument();
  });

  it('returns null for an empty company list', () => {
    const { container } = render(<LevelTree companies={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/features/visualize/charts/LevelTree.test.tsx`
Expected: FAIL — no "Impact Tree" title yet, `forceCollapse` prop doesn't exist.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/visualize/charts/LevelTree.tsx
import { useEffect, useMemo, useRef, useState } from 'react';
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { computeNetSignal, groupBySector } from '../transforms';
import { sectorColor } from '../colors';
import { IMPACT_LEVEL_ORDER, impactLevelColor, impactLevelKey, impactLevelLabel } from '../impactLevels';
import ChartCardShell from './ChartCardShell';
import ImpactCard from './cards/ImpactCard';
import CompanyRow from './cards/CompanyRow';
import { useCompanySelection } from './useCompanySelection';

export interface ForceCollapseSignal {
  mode: 'expand' | 'collapse';
  version: number;
}

interface LevelCard {
  key: string;
  label: string;
  companies: AlertCompany[];
  sectorKey?: string;
}

function groupByParent(levelCompanies: AlertCompany[], allCompanies: AlertCompany[]) {
  const byId = new Map(allCompanies.map((c) => [c.company_id, c]));
  const byParent = new Map<number, AlertCompany[]>();
  const orphaned: AlertCompany[] = [];
  for (const c of levelCompanies) {
    if (c.parent_company_id == null) {
      orphaned.push(c);
      continue;
    }
    const group = byParent.get(c.parent_company_id) ?? [];
    group.push(c);
    byParent.set(c.parent_company_id, group);
  }
  const groups = [...byParent.entries()].map(([parentId, kids]) => {
    const parent = byId.get(parentId);
    return {
      key: `parent-${parentId}`,
      label: parent ? `Via ${parent.name} (${parent.ticker})` : `Via company #${parentId}`,
      companies: kids,
    };
  });
  return { groups, orphaned };
}

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
  forceCollapse,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
  forceCollapse?: ForceCollapseSignal;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);

  const levels = useMemo(() => {
    return IMPACT_LEVEL_ORDER.map((level) => {
      const levelCompanies = companies.filter((c) => impactLevelKey(c) === level);
      let cards: LevelCard[];
      if (level === 'direct') {
        cards = groupBySector(levelCompanies).map((g) => ({ key: g.key, label: g.label, companies: g.companies, sectorKey: g.key }));
      } else {
        const { groups, orphaned } = groupByParent(levelCompanies, companies);
        cards = groups.map((g) => ({ key: `${level}-${g.key}`, label: g.label, companies: g.companies }));
        if (orphaned.length > 0) cards.push({ key: `${level}-orphaned`, label: 'Other', companies: orphaned });
      }
      return { level, companies: levelCompanies, cards };
    }).filter((l) => l.companies.length > 0);
  }, [companies]);

  const [collapsedKeys, setCollapsedKeys] = useState<Set<string>>(new Set());
  const lastVersion = useRef(0);

  useEffect(() => {
    if (!forceCollapse || forceCollapse.version === lastVersion.current) return;
    lastVersion.current = forceCollapse.version;
    if (forceCollapse.mode === 'collapse') {
      setCollapsedKeys(new Set(levels.flatMap((l) => l.cards.map((c) => c.key))));
    } else {
      setCollapsedKeys(new Set());
    }
  }, [forceCollapse, levels]);

  function toggleCard(key: string) {
    setCollapsedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  if (levels.length === 0) return null;

  return (
    <ChartCardShell
      number={1}
      title="Impact Tree"
      description="Hierarchical tree showing primary, secondary, and tertiary affected companies"
      legend={LEGEND}
    >
      <div className="flex flex-col p-4">
        {levels.map(({ level, companies: levelCompanies, cards }, i) => {
          const color = impactLevelColor(level);
          return (
            <div key={level} className="flex flex-col">
              {i > 0 && <LevelConnector />}
              <div className="mb-2 flex items-center gap-2">
                <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
                <p className="text-xs uppercase tracking-widest text-ink">{impactLevelLabel(level)}</p>
                <p className="text-xs text-muted">({levelCompanies.length})</p>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {cards.map((card) => (
                  <ImpactCard
                    key={card.key}
                    label={card.label}
                    color={card.sectorKey ? sectorColor(card.sectorKey) : color}
                    signal={computeNetSignal(card.companies)}
                    companyCount={card.companies.length}
                    collapsed={collapsedKeys.has(card.key)}
                    onToggle={() => toggleCard(card.key)}
                  >
                    {card.companies.map((c) => (
                      <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => toggle(c.company_id)} />
                    ))}
                  </ImpactCard>
                ))}
              </div>
            </div>
          );
        })}
        {selected && (
          <div className="mt-4">
            <ReasoningPanel company={selected} eventType={eventType} />
          </div>
        )}
      </div>
    </ChartCardShell>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/features/visualize/charts/LevelTree.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/LevelTree.tsx frontend/src/features/visualize/charts/LevelTree.test.tsx
git commit -m "feat: wrap LevelTree in ChartCardShell, add forceCollapse control"
```

---

### Task 4: `ConfidenceTree` — wrap in `ChartCardShell` (#5)

**Files:**
- Modify: `frontend/src/features/visualize/charts/ConfidenceTree.tsx`
- Test: `frontend/src/features/visualize/charts/ConfidenceTree.test.tsx` (new)

**Interfaces:**
- Produces: same default export signature, now rendering inside `ChartCardShell number={5} title="Confidence Tree"`. No prop changes.
- Consumes: `ChartCardShell` (Task 2).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/visualize/charts/ConfidenceTree.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ConfidenceTree from './ConfidenceTree';
import type { AlertCompany } from '../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'TEST', name: 'Test Co', index_tier: 'NIFTY50', direction: 'bullish',
    magnitude_low: 1, magnitude_high: 2, rationale: 'r', key_points: [], confidence_score: 92,
    time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('ConfidenceTree', () => {
  it('renders wrapped in ChartCardShell with number 5 and title Confidence Tree', () => {
    render(<ConfidenceTree companies={[company({})]} />);
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('Confidence Tree')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/ConfidenceTree.test.tsx`
Expected: FAIL — no "Confidence Tree" title text rendered yet.

- [ ] **Step 3: Implement** — wrap the existing return value; only the import list and the outermost JSX element change:

```tsx
// frontend/src/features/visualize/charts/ConfidenceTree.tsx
import { useLanguage } from '../../../lib/language';
import type { AlertCompany } from '../../../lib/api';
import { BAND_LABEL_KEY } from '../../../components/ConfidenceBandPill';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { computeNetSignal, rankByConfidence } from '../transforms';
import { confidenceBandColor, confidenceBandFromScore } from '../colors';
import ChartCardShell from './ChartCardShell';
import ImpactCard from './cards/ImpactCard';
import CompanyRow from './cards/CompanyRow';
import { useCompanySelection } from './useCompanySelection';

const BAND_ORDER = ['VERY_HIGH', 'HIGH', 'MODERATE', 'LOW'] as const;

export default function ConfidenceTree({
  companies,
  eventType,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { t } = useLanguage();
  const { toggle, selected, selectedId } = useCompanySelection(companies);

  if (companies.length === 0) return null;

  const groups = BAND_ORDER.map((band) => ({
    band,
    companies: rankByConfidence(companies.filter((c) => confidenceBandFromScore(c.confidence_score) === band)),
  })).filter((g) => g.companies.length > 0);

  return (
    <ChartCardShell
      number={5}
      title="Confidence Tree"
      description="Tree showing companies with confidence scores for impact"
      legend={groups.map((g) => ({ label: t(BAND_LABEL_KEY[g.band]), color: confidenceBandColor(g.band) }))}
    >
      <div className="flex flex-col gap-4 p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {groups.map((group) => (
            <ImpactCard
              key={group.band}
              label={t(BAND_LABEL_KEY[group.band])}
              color={confidenceBandColor(group.band)}
              signal={computeNetSignal(group.companies)}
              companyCount={group.companies.length}
            >
              {group.companies.map((c) => (
                <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => toggle(c.company_id)} />
              ))}
            </ImpactCard>
          ))}
        </div>
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/ConfidenceTree.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/ConfidenceTree.tsx frontend/src/features/visualize/charts/ConfidenceTree.test.tsx
git commit -m "feat: wrap ConfidenceTree in ChartCardShell"
```

---

### Task 5: `SplitTree` — wrap in `ChartCardShell` (#6 Positive/Negative Split)

**Files:**
- Modify: `frontend/src/features/visualize/charts/SplitTree.tsx`
- Test: `frontend/src/features/visualize/charts/SplitTree.test.tsx` (new)

**Interfaces:**
- Produces: same default export signature, wrapped in `ChartCardShell number={6} title="Positive / Negative Split"`.
- Consumes: `ChartCardShell` (Task 2).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/visualize/charts/SplitTree.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SplitTree from './SplitTree';
import type { AlertCompany } from '../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'TEST', name: 'Test Co', index_tier: 'NIFTY50', direction: 'bullish',
    magnitude_low: 1, magnitude_high: 2, rationale: 'r', key_points: [], confidence_score: 80,
    time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('SplitTree', () => {
  it('renders wrapped in ChartCardShell with number 6 and title Positive / Negative Split', () => {
    render(<SplitTree companies={[company({})]} />);
    expect(screen.getByText('6')).toBeInTheDocument();
    expect(screen.getByText('Positive / Negative Split')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/SplitTree.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/visualize/charts/SplitTree.tsx
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { rankByMagnitude } from '../transforms';
import ChartCardShell from './ChartCardShell';
import CompanyRow from './cards/CompanyRow';
import { useCompanySelection } from './useCompanySelection';

function SplitColumn({
  title,
  tone,
  companies,
  selectedId,
  onSelect,
}: {
  title: string;
  tone: 'bullish' | 'bearish';
  companies: AlertCompany[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  if (companies.length === 0) return null;
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-hairline p-3.5 theme-light:border-transparent theme-light:shadow-neu-sm">
      <div className="flex items-center justify-between">
        <p className={`text-xs uppercase tracking-widest ${tone === 'bullish' ? 'text-bullish' : 'text-bearish'}`}>{title}</p>
        <span className="text-xs text-muted">{companies.length}</span>
      </div>
      <div className="flex flex-col gap-1">
        {companies.map((c) => (
          <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => onSelect(c.company_id)} />
        ))}
      </div>
    </div>
  );
}

export default function SplitTree({
  companies,
  eventType,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const bullish = rankByMagnitude(companies.filter((c) => c.direction === 'bullish'));
  const bearish = rankByMagnitude(companies.filter((c) => c.direction === 'bearish'));

  if (bullish.length === 0 && bearish.length === 0) return null;

  return (
    <ChartCardShell
      number={6}
      title="Positive / Negative Split"
      description="Clear separation of positive and negative impact"
      legend={[
        { label: 'Positive Impact', color: '#34C759' },
        { label: 'Negative Impact', color: '#FF453A' },
      ]}
    >
      <div className="flex flex-col gap-3 p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <SplitColumn title="Positive Impact" tone="bullish" companies={bullish} selectedId={selectedId} onSelect={toggle} />
          <SplitColumn title="Negative Impact" tone="bearish" companies={bearish} selectedId={selectedId} onSelect={toggle} />
        </div>
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/SplitTree.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/SplitTree.tsx frontend/src/features/visualize/charts/SplitTree.test.tsx
git commit -m "feat: wrap SplitTree in ChartCardShell"
```

---

### Task 6: `TimelineTree` — wrap in `ChartCardShell` (#7)

**Files:**
- Modify: `frontend/src/features/visualize/charts/TimelineTree.tsx`
- Test: `frontend/src/features/visualize/charts/TimelineTree.test.tsx` (new)

**Interfaces:**
- Produces: same default export signature, wrapped in `ChartCardShell number={7} title="Timeline Tree"`.
- Consumes: `ChartCardShell` (Task 2).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/visualize/charts/TimelineTree.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import TimelineTree from './TimelineTree';
import type { AlertCompany } from '../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'TEST', name: 'Test Co', index_tier: 'NIFTY50', direction: 'bullish',
    magnitude_low: 1, magnitude_high: 2, rationale: 'r', key_points: [], confidence_score: 80,
    time_horizon: 'Immediate', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('TimelineTree', () => {
  it('renders wrapped in ChartCardShell with number 7 and title Timeline Tree', () => {
    render(<TimelineTree companies={[company({})]} />);
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText('Timeline Tree')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/TimelineTree.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/visualize/charts/TimelineTree.tsx
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { groupByTimeHorizon } from '../transforms';
import ChartCardShell from './ChartCardShell';
import CompanyRow from './cards/CompanyRow';
import { useCompanySelection } from './useCompanySelection';

const HORIZON_CAPTION: Record<string, string> = {
  Immediate: 'Already priced in, or resolves within days',
  'Short-Term': 'Plays out over the next few weeks to a quarter',
  'Medium-Term': 'Multi-quarter',
  'Long-Term': 'Structural, multi-year',
};

export default function TimelineTree({
  companies,
  eventType,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const groups = groupByTimeHorizon(companies);

  if (groups.length === 0) return null;

  return (
    <ChartCardShell number={7} title="Timeline Tree" description="Impact progression over different time horizons">
      <div className="flex flex-col p-4">
        {groups.map((group, i) => (
          <div key={group.key} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span aria-hidden="true" className="mt-1 h-3 w-3 shrink-0 rounded-full bg-ink" />
              {i < groups.length - 1 && <span aria-hidden="true" className="w-px flex-1 bg-hairline" />}
            </div>
            <div className="flex-1 pb-4">
              <p className="text-xs uppercase tracking-widest text-ink">{group.label}</p>
              <p className="mt-0.5 text-xs text-muted">{HORIZON_CAPTION[group.key] ?? ''}</p>
              <div className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
                {group.companies.map((c) => (
                  <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => toggle(c.company_id)} />
                ))}
              </div>
            </div>
          </div>
        ))}
        {selected && (
          <div className="mt-2">
            <ReasoningPanel company={selected} eventType={eventType} />
          </div>
        )}
      </div>
    </ChartCardShell>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/TimelineTree.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/TimelineTree.tsx frontend/src/features/visualize/charts/TimelineTree.test.tsx
git commit -m "feat: wrap TimelineTree in ChartCardShell"
```

---

### Task 7: `SectorTree` — wrap in `ChartCardShell` (#8)

**Files:**
- Modify: `frontend/src/features/visualize/charts/SectorTree.tsx`
- Test: `frontend/src/features/visualize/charts/SectorTree.test.tsx` (new)

**Interfaces:**
- Produces: same default export signature, wrapped in `ChartCardShell number={8} title="Sector Tree"`.
- Consumes: `ChartCardShell` (Task 2).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/visualize/charts/SectorTree.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SectorTree from './SectorTree';
import type { AlertCompany } from '../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'TEST', name: 'Test Co', index_tier: 'NIFTY50', direction: 'bullish',
    magnitude_low: 1, magnitude_high: 2, rationale: 'r', key_points: [], confidence_score: 80,
    time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [], sector: 'banking',
    ...overrides,
  };
}

describe('SectorTree', () => {
  it('renders wrapped in ChartCardShell with number 8 and title Sector Tree', () => {
    render(<SectorTree companies={[company({})]} />);
    expect(screen.getByText('8')).toBeInTheDocument();
    expect(screen.getByText('Sector Tree')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/SectorTree.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement**

```tsx
// frontend/src/features/visualize/charts/SectorTree.tsx
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { groupBySectorAndSubSector } from '../transforms';
import ChartCardShell from './ChartCardShell';
import ImpactCard from './cards/ImpactCard';
import CompanyRow from './cards/CompanyRow';
import { useCompanySelection } from './useCompanySelection';

export default function SectorTree({
  companies,
  eventType,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const sectors = groupBySectorAndSubSector(companies);

  if (sectors.length === 0) return null;

  return (
    <ChartCardShell number={8} title="Sector Tree" description="Impact organized by sectors and sub-sectors">
      <div className="flex flex-col gap-4 p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {sectors.map((sector) => (
            <ImpactCard
              key={sector.key}
              label={sector.label}
              color={sector.color ?? '#557C30'}
              signal={sector.netSignal}
              companyCount={sector.companies.length}
            >
              {sector.subSectorGroups.length <= 1
                ? sector.companies.map((c) => (
                    <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => toggle(c.company_id)} />
                  ))
                : sector.subSectorGroups.map((sub) => (
                    <div key={sub.key} className="flex flex-col gap-0.5">
                      <p className="px-2 pt-1.5 text-[11px] uppercase tracking-widest text-muted">{sub.label}</p>
                      {sub.companies.map((c) => (
                        <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => toggle(c.company_id)} />
                      ))}
                    </div>
                  ))}
            </ImpactCard>
          ))}
        </div>
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/SectorTree.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/SectorTree.tsx frontend/src/features/visualize/charts/SectorTree.test.tsx
git commit -m "feat: wrap SectorTree in ChartCardShell"
```

---

### Task 8: `AlertChartsPage` — Normal View: "Directly Affected Sectors" grid + Impact Summary banner

**Files:**
- Modify: `frontend/src/pages/AlertChartsPage.tsx`
- Test: `frontend/src/pages/AlertChartsPage.test.tsx` (new — none exists today; check with `ls frontend/src/pages/*.test.tsx` before writing to confirm, and follow the existing routing-test pattern used elsewhere in `frontend/src/pages/` if one exists, e.g. wrapping in `MemoryRouter`)

**Interfaces:**
- Produces: `AlertChartsPage` (default export, no props — reads `useParams`) gains two new page-level sections rendered above the existing chart-tab carousel, only in Normal breadth: a sector-card grid (`groupBySector` over `visibleCompanies`, each card using `ImpactCard` with `onViewDetails`) and an Impact Summary banner.
- Consumes: `ImpactCard` (Task 1), `groupBySector`/`computeNetSignal`/`rankByConfidence` from `../features/visualize/transforms` (all already exist), `useCompanySelection` from `../features/visualize/charts/useCompanySelection`, `ReasoningPanel`, `CompanyRow` from `../features/visualize/charts/cards/CompanyRow`, `Link` from `react-router-dom`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/AlertChartsPage.test.tsx
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import AlertChartsPage from './AlertChartsPage';
import * as api from '../lib/api';

vi.mock('../lib/auth', () => ({ useAuth: () => ({ token: null }) }));
vi.mock('../lib/language', () => ({ useLanguage: () => ({ language: 'en', t: (k: string) => k }) }));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/alerts/1/charts']}>
      <Routes>
        <Route path="/alerts/:id/charts" element={<AlertChartsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('AlertChartsPage Normal View', () => {
  it('renders a Directly Affected Sectors section and an Impact Summary banner from real alert data', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue({
      id: 1,
      category: 'banking',
      category_label: 'Banking',
      created_at: '2026-07-17T00:00:00Z',
      article: { id: 1, title: 'RBI cuts repo rate', url: 'https://example.com', image_url: null },
      event_type: 'repo_rate_change',
      companies: [
        {
          company_id: 1, ticker: 'HDFCBANK', name: 'HDFC Bank', index_tier: 'NIFTY50', sector: 'banking',
          direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'lower funding cost',
          key_points: [], confidence_score: 90, time_horizon: 'Short-Term', basis: 'direct_mention',
          confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [], impact_level: 'direct',
        },
      ],
    } as api.Alert);

    renderPage();

    await waitFor(() => expect(screen.getByText('Directly Affected Sectors')).toBeInTheDocument());
    expect(screen.getByText('Impact Summary')).toBeInTheDocument();
    expect(screen.getByText('HDFCBANK')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/AlertChartsPage.test.tsx`
Expected: FAIL — "Directly Affected Sectors" / "Impact Summary" text doesn't exist yet.

- [ ] **Step 3: Implement** — full new file:

```tsx
// frontend/src/pages/AlertChartsPage.tsx
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { getAlert, type Alert, type AlertCompany } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
import { useHorizontalSwipe } from '../lib/useHorizontalSwipe';
import { computeNetSignal, groupBySector, rankByConfidence } from '../features/visualize/transforms';
import { impactLevelKey } from '../features/visualize/impactLevels';
import { useCompanySelection } from '../features/visualize/charts/useCompanySelection';
import ImpactCard from '../features/visualize/charts/cards/ImpactCard';
import CompanyRow from '../features/visualize/charts/cards/CompanyRow';
import ReasoningPanel from '../components/ReasoningPanel';
import SectorTree from '../features/visualize/charts/SectorTree';
import TierRows from '../features/visualize/charts/TierRows';
import ImpactBar from '../features/visualize/charts/ImpactBar';
import SplitTree from '../features/visualize/charts/SplitTree';
import ConfidenceTree from '../features/visualize/charts/ConfidenceTree';
import TimelineTree from '../features/visualize/charts/TimelineTree';
import LevelTree from '../features/visualize/charts/LevelTree';

// Numbered prefixes match the reference mockup's chart numbering for the 5
// charts restyled this round. `tier`/`impact` have no mockup number (see the
// design spec's "Correction" section -- their fate is decided in the
// follow-up plan) so they keep plain labels rather than an invented number.
const CHARTS = [
  { key: 'levels', label: '1 · Impact Tree', Component: LevelTree },
  { key: 'tier', label: 'Tier', Component: TierRows },
  { key: 'impact', label: 'Impact', Component: ImpactBar },
  { key: 'confidence', label: '5 · Confidence', Component: ConfidenceTree },
  { key: 'split', label: '6 · Split', Component: SplitTree },
  { key: 'timeline', label: '7 · Timeline', Component: TimelineTree },
  { key: 'sector', label: '8 · Sector', Component: SectorTree },
] as const;

type Breadth = 'normal' | 'drilldown';

function StatTile({ label, value, valueClass, caption }: { label: string; value: string; valueClass?: string; caption?: string }) {
  return (
    <div className="flex min-w-[7rem] flex-1 flex-col gap-1 rounded-xl border border-hairline p-3 theme-light:border-transparent theme-light:shadow-neu-sm">
      <p className="text-[11px] uppercase tracking-widest text-muted">{label}</p>
      <p className={`text-lg font-medium ${valueClass ?? 'text-ink'}`}>{value}</p>
      {caption && <p className="text-[11px] text-muted">{caption}</p>}
    </div>
  );
}

function StatBar({ companies, breadth }: { companies: AlertCompany[]; breadth: Breadth }) {
  const signal = computeNetSignal(companies);
  const sectorCount = new Set(companies.map((c) => c.sector).filter(Boolean)).size;
  const subSectorCount = new Set(companies.map((c) => c.sub_sector).filter(Boolean)).size;
  const levelCounts = { direct: 0, indirect_l1: 0, indirect_l2: 0 } as Record<string, number>;
  for (const c of companies) levelCounts[impactLevelKey(c)] += 1;

  const overallLabel = signal.direction === 'even' ? 'Mixed' : signal.direction === 'bullish' ? 'Bullish' : 'Bearish';
  const overallGlyph = signal.direction === 'even' ? '▬' : signal.direction === 'bullish' ? '▲' : '▼';
  const overallClass = signal.direction === 'even' ? 'text-muted' : signal.direction === 'bullish' ? 'text-bullish' : 'text-bearish';

  return (
    <div className="flex flex-wrap gap-2.5 border-b border-hairline p-4">
      <StatTile
        label="Overall Impact"
        value={`${overallGlyph} ${overallLabel}`}
        valueClass={overallClass}
        caption={`${signal.avgConfidence}% confidence`}
      />
      <StatTile label="Affected Sectors" value={String(sectorCount)} />
      <StatTile label="Affected Categories" value={String(subSectorCount)} caption={subSectorCount === 0 ? 'Unclassified' : undefined} />
      <StatTile label="Affected Companies" value={String(companies.length)} />
      {breadth === 'drilldown' && (
        <StatTile
          label="By Level"
          value={`${levelCounts.direct} / ${levelCounts.indirect_l1} / ${levelCounts.indirect_l2}`}
          caption="Direct / Indirect L1 / Indirect L2"
        />
      )}
    </div>
  );
}

function DirectlyAffectedSectors({
  companies,
  selectedId,
  onSelect,
}: {
  companies: AlertCompany[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const sectors = groupBySector(companies);
  if (sectors.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 border-b border-hairline p-4">
      <p className="text-xs uppercase tracking-widest text-muted">Directly Affected Sectors</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {sectors.map((sector) => (
          <ImpactCard
            key={sector.key}
            label={sector.label}
            color={sector.color ?? '#557C30'}
            signal={computeNetSignal(sector.companies)}
            companyCount={sector.companies.length}
            onViewDetails={() => onSelect(sector.companies[0].company_id)}
          >
            {sector.companies.map((c) => (
              <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => onSelect(c.company_id)} />
            ))}
          </ImpactCard>
        ))}
      </div>
    </div>
  );
}

function ImpactSummaryBanner({ companies, alertId, title }: { companies: AlertCompany[]; alertId: number; title: string }) {
  if (companies.length === 0) return null;
  const sectors = groupBySector(companies);
  const topSector = [...sectors].sort((a, b) => b.companies.length - a.companies.length)[0];
  const top = rankByConfidence(companies)[0];
  const signal = computeNetSignal(companies);
  const outlook = signal.direction === 'even' ? 'a mixed' : signal.direction === 'bullish' ? 'a bullish' : 'a bearish';

  return (
    <div className="flex flex-col gap-2 border-b border-hairline p-4">
      <p className="text-xs uppercase tracking-widest text-muted">{title}</p>
      <p className="text-sm text-ink">
        This event points to {outlook} outlook concentrated in {topSector.label} (
        {topSector.companies.length} {topSector.companies.length === 1 ? 'company' : 'companies'}), at{' '}
        {signal.avgConfidence}% average confidence.
      </p>
      <Link to={`/alerts/${alertId}/company/${top.company_id}`} className="self-start text-xs text-muted hover:text-ink">
        View Full Analysis →
      </Link>
    </div>
  );
}

export default function AlertChartsPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { token } = useAuth();
  const { language } = useLanguage();
  const [alert, setAlert] = useState<Alert | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [breadth, setBreadth] = useState<Breadth>('normal');

  useEffect(() => {
    if (!id) return;
    let active = true;
    getAlert(Number(id), token, language)
      .then((data) => {
        if (active) setAlert(data);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'Failed to load alert.');
      });
    return () => {
      active = false;
    };
  }, [id, token, language]);

  const swipeHandlers = useHorizontalSwipe({
    onSwipeLeft: () => setIndex((i) => Math.min(i + 1, CHARTS.length - 1)),
    onSwipeRight: () => (index === 0 ? navigate(-1) : setIndex((i) => Math.max(i - 1, 0))),
  });

  const visibleCompanies =
    alert == null
      ? []
      : breadth === 'normal'
        ? alert.companies.filter((c) => impactLevelKey(c) === 'direct')
        : alert.companies;

  const { toggle, selected, selectedId } = useCompanySelection(visibleCompanies);

  if (error) {
    return <p className="p-4 text-xs uppercase tracking-widest text-bearish">{error}</p>;
  }
  if (!alert) {
    return <p className="p-4 text-xs uppercase tracking-widest text-muted">Loading…</p>;
  }

  const { Component } = CHARTS[index];

  return (
    <div className="flex min-h-screen flex-col bg-page" {...swipeHandlers}>
      <div className="flex items-center gap-3 border-b border-hairline p-4">
        <button type="button" onClick={() => navigate(-1)} aria-label="Back" className="text-muted hover:text-ink">
          ←
        </button>
        <h1 className="truncate text-sm text-ink">{alert.article.title}</h1>
        <div className="ml-auto flex gap-1 self-start rounded-md border border-hairline bg-surface p-0.5">
          {(['normal', 'drilldown'] as Breadth[]).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setBreadth(mode)}
              className={`rounded px-2 py-0.5 text-[11px] uppercase tracking-widest ${
                breadth === mode ? 'bg-page text-ink' : 'text-muted'
              }`}
            >
              {mode === 'normal' ? 'Normal' : 'Drilldown'}
            </button>
          ))}
        </div>
      </div>
      <StatBar companies={visibleCompanies} breadth={breadth} />
      {visibleCompanies.length === 0 ? (
        <p className="p-4 text-xs uppercase tracking-widest text-muted">
          No directly-confirmed companies for this alert — try Drilldown for the wider sector picture.
        </p>
      ) : (
        breadth === 'normal' && (
          <>
            <DirectlyAffectedSectors companies={visibleCompanies} selectedId={selectedId} onSelect={toggle} />
            {selected && (
              <div className="border-b border-hairline p-4">
                <ReasoningPanel company={selected} eventType={alert.event_type} />
              </div>
            )}
            <ImpactSummaryBanner companies={visibleCompanies} alertId={alert.id} title="Impact Summary" />
          </>
        )
      )}
      <div className="flex gap-4 overflow-x-auto border-b border-hairline px-4 py-2">
        {CHARTS.map((chart, i) => (
          <button
            key={chart.key}
            type="button"
            onClick={() => setIndex(i)}
            className={`text-xs uppercase tracking-widest ${i === index ? 'text-ink' : 'text-muted'}`}
          >
            {chart.label}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto">
        {visibleCompanies.length > 0 && <Component companies={visibleCompanies} eventType={alert.event_type} />}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/AlertChartsPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Run the full frontend test suite to catch any incidental regression**

Run: `cd frontend && npx vitest run`
Expected: PASS across the board.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/AlertChartsPage.tsx frontend/src/pages/AlertChartsPage.test.tsx
git commit -m "feat: add Directly Affected Sectors grid and Impact Summary banner to Normal View"
```

---

### Task 9: `AlertChartsPage` — Drilldown View: pinned `LevelTree` overview + Expand All/Collapse All + Full Impact Summary

**Files:**
- Modify: `frontend/src/pages/AlertChartsPage.tsx`
- Modify: `frontend/src/pages/AlertChartsPage.test.tsx`

**Interfaces:**
- Produces: in `breadth === 'drilldown'`, the page renders `<LevelTree companies={visibleCompanies} eventType={alert.event_type} forceCollapse={forceCollapse} />` pinned above the chart-tab carousel, preceded by Expand All/Collapse All buttons and followed by an `ImpactSummaryBanner` titled "Full Impact Summary".
- Consumes: `LevelTree`'s `ForceCollapseSignal` type and `forceCollapse` prop (Task 3).

**Known simplification (documented, not hidden):** the pinned Drilldown overview reuses the exact same `LevelTree` component that's also reachable via the "Levels" tab further down — this means the Impact Tree view is visible twice in Drilldown mode (once pinned, once in the carousel). This is intentional reuse, not a bug: `LevelTree`'s direct/L1/L2 grouping *is* the real content of the mockup's Drilldown overview, and building a second, visually-different component with identical data/logic just to avoid the duplication is unjustified complexity for this plan. Revisit only if user feedback says the duplication reads as broken.

- [ ] **Step 1: Write the failing test**

```tsx
// append to frontend/src/pages/AlertChartsPage.test.tsx, inside a new describe block

describe('AlertChartsPage Drilldown View', () => {
  it('shows Expand All / Collapse All controls and a Full Impact Summary banner', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue({
      id: 1,
      category: 'banking',
      category_label: 'Banking',
      created_at: '2026-07-17T00:00:00Z',
      article: { id: 1, title: 'RBI cuts repo rate', url: 'https://example.com', image_url: null },
      event_type: 'repo_rate_change',
      companies: [
        {
          company_id: 1, ticker: 'HDFCBANK', name: 'HDFC Bank', index_tier: 'NIFTY50', sector: 'banking',
          direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'lower funding cost',
          key_points: [], confidence_score: 90, time_horizon: 'Short-Term', basis: 'direct_mention',
          confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [], impact_level: 'direct',
        },
      ],
    } as api.Alert);

    renderPage();
    await waitFor(() => expect(screen.getByText('RBI cuts repo rate')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /drilldown/i }));

    expect(screen.getByRole('button', { name: /expand all/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /collapse all/i })).toBeInTheDocument();
    expect(screen.getByText('Full Impact Summary')).toBeInTheDocument();
  });
});
```

Add `fireEvent` to the existing `@testing-library/react` import at the top of the test file.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/AlertChartsPage.test.tsx`
Expected: FAIL — no Expand All/Collapse All buttons, no "Full Impact Summary" text yet.

- [ ] **Step 3: Implement** — three edits to `AlertChartsPage.tsx` from Task 8's version:

Add to the imports:
```tsx
import LevelTree, { type ForceCollapseSignal } from '../features/visualize/charts/LevelTree';
```
(replacing the plain `import LevelTree from '../features/visualize/charts/LevelTree';` line)

Add state inside the component, alongside the existing `useState` calls:
```tsx
const [forceCollapse, setForceCollapse] = useState<ForceCollapseSignal | undefined>(undefined);
const [collapseVersion, setCollapseVersion] = useState(0);

function expandAll() {
  const next = collapseVersion + 1;
  setCollapseVersion(next);
  setForceCollapse({ mode: 'expand', version: next });
}

function collapseAll() {
  const next = collapseVersion + 1;
  setCollapseVersion(next);
  setForceCollapse({ mode: 'collapse', version: next });
}
```

Replace the Normal-View-only conditional block with one that branches on `breadth`:
```tsx
{visibleCompanies.length === 0 ? (
  <p className="p-4 text-xs uppercase tracking-widest text-muted">
    No directly-confirmed companies for this alert — try Drilldown for the wider sector picture.
  </p>
) : breadth === 'normal' ? (
  <>
    <DirectlyAffectedSectors companies={visibleCompanies} selectedId={selectedId} onSelect={toggle} />
    {selected && (
      <div className="border-b border-hairline p-4">
        <ReasoningPanel company={selected} eventType={alert.event_type} />
      </div>
    )}
    <ImpactSummaryBanner companies={visibleCompanies} alertId={alert.id} title="Impact Summary" />
  </>
) : (
  <>
    <div className="flex items-center justify-end gap-3 border-b border-hairline px-4 py-2 text-xs">
      <button type="button" onClick={expandAll} className="text-muted hover:text-ink">
        Expand All
      </button>
      <button type="button" onClick={collapseAll} className="text-muted hover:text-ink">
        Collapse All
      </button>
    </div>
    <LevelTree companies={visibleCompanies} eventType={alert.event_type} forceCollapse={forceCollapse} />
    <ImpactSummaryBanner companies={visibleCompanies} alertId={alert.id} title="Full Impact Summary" />
  </>
)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/AlertChartsPage.test.tsx`
Expected: PASS (both describe blocks)

- [ ] **Step 5: Run the full frontend test suite**

Run: `cd frontend && npx vitest run`
Expected: PASS across the board.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/AlertChartsPage.tsx frontend/src/pages/AlertChartsPage.test.tsx
git commit -m "feat: add pinned LevelTree overview with Expand All/Collapse All to Drilldown View"
```

---

## After this plan

`TierRows`/`ImpactBar` stay in the chart-tab carousel unrestyled (out of scope, see Global Constraints). The follow-up plan (not yet written) covers: the backend `economic_chain` field, and the four genuinely new chart components (Ripple Effect Graph, Multi-Level Impact Tree, Supply Chain Graph, Knowledge Graph) — at which point `TierRows`/`ImpactBar`'s retirement is finalized alongside them, per the design spec's "Correction" section.
