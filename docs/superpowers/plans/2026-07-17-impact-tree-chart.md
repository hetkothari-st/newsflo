# Impact Tree Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the first chart in `AlertChartsPage` — a "Multi-Level Impact Tree" showing the news item, its directly-affected sectors and companies, and the indirect ripple effect on other sub-sectors and companies, all real data.

**Architecture:** One new self-contained chart component (`ImpactTree.tsx`, wraps itself in `ChartCardShell` per existing chart convention) plus one new pure data-grouping transform (`groupIndirectBySubSector`). Wired into `AlertChartsPage.tsx` in place of the current blank trailing `<div>`.

**Tech Stack:** React 18 + TypeScript (Vite), Tailwind CSS, Vitest + React Testing Library. No charting library — hand-rolled CSS layout, per existing project convention.

## Global Constraints

- Real data only — every card must trace to an actual `AlertCompany` row. No fabricated index/market data (spec explicitly rejected a "wider market impact" level for this reason).
- No new chart library / no SVG node-link diagrams — straight CSS/Tailwind layout only, matching every other chart in `frontend/src/features/visualize/charts/`.
- Always fully expanded, page scrolls vertically — no collapse/expand interaction in this version.
- Single chart only — no pager/tab scaffold. `AlertChartsPage` renders `ImpactTree` directly.
- Dark (default) + light (`.light` neumorphic) theme both supported via existing CSS vars/utility classes only (`border-hairline`, `text-muted`, `text-ink`, `text-bullish`/`text-bearish`, `theme-light:shadow-neu`/`theme-light:shadow-neu-sm`, `font-editorial`, `font-data`). No new colors.
- No emoji anywhere — glyphs only (`▲`/`▼`/`▼` connector), consistent with `InsightCard`/`SectorTree`.
- Level 1/2 = direct-impact companies grouped by `sector`. Level 3/4 = indirect (`indirect_l1` + `indirect_l2` collapsed together) companies grouped by `sub_sector`, using the existing `subSectorKey`/`subSectorLabel`/`UNCLASSIFIED_KEY` helpers (not a fallback to sector name — this matches the established pattern in `groupBySectorAndSubSector` instead of inventing a new one).
- Company cards show `confidence_score`% (a real 0-100 field), not `magnitude_low`/`magnitude_high` — `transforms.ts`'s existing comment on `rankByMagnitude` documents magnitude as ordinal-only, not a real percentage, so surfacing it as "-1.45%" (as in the reference mockup) would be a fabricated number. This is a deliberate deviation from the design spec's literal "magnitude %" wording, in service of the spec's own real-data-only requirement.

---

### Task 1: `groupIndirectBySubSector` transform

**Files:**
- Modify: `frontend/src/features/visualize/transforms.ts`
- Test: `frontend/src/features/visualize/transforms.test.ts`

**Interfaces:**
- Consumes: `AlertCompany` (`frontend/src/lib/api.ts`), `impactLevelKey` (`./impactLevels`), `subSectorKey`/`subSectorLabel`/`UNCLASSIFIED_KEY` (`./subSectorLabels`), `computeNetSignal` and the existing `SubSectorGroup` interface (both already in `transforms.ts`).
- Produces: `groupIndirectBySubSector(companies: AlertCompany[]): SubSectorGroup[]` — later consumed by Task 2's `ImpactTree.tsx`.

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `frontend/src/features/visualize/transforms.test.ts` (add `groupIndirectBySubSector` to the existing top-of-file import list from `./transforms`):

```ts
describe('groupIndirectBySubSector', () => {
  it('excludes direct-impact companies, keeping only indirect_l1/indirect_l2', () => {
    const groups = groupIndirectBySubSector([
      company({ company_id: 1, impact_level: 'direct', sector: 'banking', sub_sector: 'private_bank' }),
      company({ company_id: 2, impact_level: 'indirect_l1', sector: 'banking', sub_sector: 'nbfc' }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe('NBFC');
    expect(groups[0].companies.map((c) => c.company_id)).toEqual([2]);
  });

  it('groups indirect_l1 and indirect_l2 companies together under the same sub_sector', () => {
    const groups = groupIndirectBySubSector([
      company({ company_id: 1, impact_level: 'indirect_l1', sub_sector: 'nbfc' }),
      company({ company_id: 2, impact_level: 'indirect_l2', sub_sector: 'nbfc' }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].companies.map((c) => c.company_id)).toEqual([1, 2]);
  });

  it('buckets a null sub_sector as Unclassified rather than dropping it', () => {
    const groups = groupIndirectBySubSector([
      company({ company_id: 1, impact_level: 'indirect_l1', sub_sector: null }),
    ]);
    expect(groups.map((g) => g.label)).toEqual(['Unclassified']);
  });

  it('returns an empty array when there are no indirect companies', () => {
    expect(groupIndirectBySubSector([company({ impact_level: 'direct' })])).toEqual([]);
  });

  it('includes a netSignal computed from the group\'s companies', () => {
    const groups = groupIndirectBySubSector([
      company({ company_id: 1, impact_level: 'indirect_l1', sub_sector: 'nbfc', direction: 'bullish' }),
      company({ company_id: 2, impact_level: 'indirect_l1', sub_sector: 'nbfc', direction: 'bullish' }),
    ]);
    expect(groups[0].netSignal.direction).toBe('bullish');
    expect(groups[0].netSignal.bullishCount).toBe(2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/transforms.test.ts`
Expected: FAIL with `groupIndirectBySubSector is not exported` / not a function.

- [ ] **Step 3: Implement `groupIndirectBySubSector`**

Add to `frontend/src/features/visualize/transforms.ts`. First update the top import line to add `subSectorKey`, `subSectorLabel`, `UNCLASSIFIED_KEY` (the file already imports `subSectorKey, subSectorLabel, UNCLASSIFIED_KEY` from `./subSectorLabels` at line 3 — confirm, don't duplicate). Also add `impactLevelKey` to a new import from `./impactLevels`:

```ts
import { impactLevelKey } from './impactLevels';
```

Then append this function after `groupBySectorAndSubSector` (end of file):

```ts
// Level 3/4 of the Impact Tree chart: the indirect ripple (indirect_l1 +
// indirect_l2 collapsed together -- the model has no L3+ level) grouped by
// sub_sector, reusing the same subSectorKey/subSectorLabel/UNCLASSIFIED_KEY
// fallback as groupBySectorAndSubSector rather than inventing a new one.
export function groupIndirectBySubSector(companies: AlertCompany[]): SubSectorGroup[] {
  const indirect = companies.filter((c) => impactLevelKey(c) !== 'direct');
  const bySub = new Map<string, AlertCompany[]>();
  for (const c of indirect) {
    const key = subSectorKey(c.sub_sector);
    const group = bySub.get(key) ?? [];
    group.push(c);
    bySub.set(key, group);
  }
  return [...bySub.entries()]
    .sort(([a], [b]) =>
      subSectorLabel(a === UNCLASSIFIED_KEY ? null : a).localeCompare(
        subSectorLabel(b === UNCLASSIFIED_KEY ? null : b),
      ),
    )
    .map(([key, group]) => ({
      key,
      label: subSectorLabel(key === UNCLASSIFIED_KEY ? null : key),
      companies: group,
      netSignal: computeNetSignal(group),
    }));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/transforms.test.ts`
Expected: PASS (all tests in the file, including the 5 new ones).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/transforms.ts frontend/src/features/visualize/transforms.test.ts
git commit -m "feat: add groupIndirectBySubSector transform for impact tree chart"
```

---

### Task 2: `ImpactTree` chart component

**Files:**
- Create: `frontend/src/features/visualize/charts/ImpactTree.tsx`
- Test: `frontend/src/features/visualize/charts/ImpactTree.test.tsx`

**Interfaces:**
- Consumes: `AlertArticle`, `AlertCompany` (`../../../lib/api`); `impactLevelKey` (`../impactLevels`); `groupBySector`, `groupIndirectBySubSector`, `CompanyGroup`, `SubSectorGroup` (`../transforms`, `groupIndirectBySubSector` from Task 1); `ChartCardShell` (`./ChartCardShell`).
- Produces: `export default function ImpactTree({ companies, article, alertCreatedAt }: { companies: AlertCompany[]; article: AlertArticle; alertCreatedAt: string })` — consumed by Task 3's `AlertChartsPage.tsx`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/charts/ImpactTree.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ImpactTree from './ImpactTree';
import type { AlertArticle, AlertCompany } from '../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50', sector: 'oil_gas',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', confidence_score: 50,
    time_horizon: 'Short-Term', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

const article: AlertArticle = { id: 1, title: 'RBI increases repo rate by 25 bps', url: 'https://example.com', image_url: null };

describe('ImpactTree', () => {
  it('renders wrapped in ChartCardShell with number 1 and title Multi-Level Impact Tree', () => {
    render(<ImpactTree companies={[]} article={article} alertCreatedAt="2026-07-17T10:30:00Z" />);
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('Multi-Level Impact Tree')).toBeInTheDocument();
  });

  it('renders the news article title', () => {
    render(<ImpactTree companies={[]} article={article} alertCreatedAt="2026-07-17T10:30:00Z" />);
    expect(screen.getByText('RBI increases repo rate by 25 bps')).toBeInTheDocument();
  });

  it('renders a direct-impact sector and its company as Level 1/2', () => {
    render(
      <ImpactTree
        companies={[company({ company_id: 1, impact_level: 'direct', sector: 'banking', ticker: 'HDFCBANK' })]}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('Banking')).toBeInTheDocument();
    expect(screen.getByText('HDFCBANK')).toBeInTheDocument();
  });

  it('renders an indirect company\'s sub-sector and ticker as Level 3/4', () => {
    render(
      <ImpactTree
        companies={[
          company({ company_id: 1, impact_level: 'indirect_l1', sector: 'banking', sub_sector: 'nbfc', ticker: 'BAJFINANCE' }),
        ]}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('NBFC')).toBeInTheDocument();
    expect(screen.getByText('BAJFINANCE')).toBeInTheDocument();
  });

  it('shows an empty note instead of Level 3/4 when there are no indirect companies', () => {
    render(
      <ImpactTree
        companies={[company({ company_id: 1, impact_level: 'direct' })]}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('No indirect ripple effects identified.')).toBeInTheDocument();
  });

  it('shows an empty note instead of Level 1/2 when there are no direct companies', () => {
    render(
      <ImpactTree
        companies={[company({ company_id: 1, impact_level: 'indirect_l1', sub_sector: 'nbfc' })]}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('No direct impact identified.')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/ImpactTree.test.tsx`
Expected: FAIL with `Failed to resolve import "./ImpactTree"`.

- [ ] **Step 3: Implement `ImpactTree.tsx`**

Create `frontend/src/features/visualize/charts/ImpactTree.tsx`:

```tsx
import type { AlertArticle, AlertCompany } from '../../../lib/api';
import { impactLevelKey } from '../impactLevels';
import { groupBySector, groupIndirectBySubSector, type CompanyGroup, type SubSectorGroup } from '../transforms';
import ChartCardShell from './ChartCardShell';

function Connector() {
  return (
    <div aria-hidden="true" className="flex flex-col items-center text-muted">
      <span className="h-3 w-px bg-hairline" />
      <span className="text-xs leading-none">▼</span>
    </div>
  );
}

function EmptyLevelNote({ text }: { text: string }) {
  return <p className="px-1 font-data text-xs uppercase tracking-widest text-muted">{text}</p>;
}

function NewsNode({ article, alertCreatedAt }: { article: AlertArticle; alertCreatedAt: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-hairline p-4 theme-light:border-transparent theme-light:shadow-neu">
      <span className="font-data text-[11px] uppercase tracking-widest text-muted">News</span>
      <p className="font-editorial text-base text-ink">{article.title}</p>
      <span className="font-data text-[11px] text-muted">
        {new Date(alertCreatedAt).toLocaleString(undefined, {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        })}
      </span>
    </div>
  );
}

function LevelHeader({ level, name, count, color }: { level: string; name: string; count: number; color?: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-hairline px-3 py-2 theme-light:border-transparent theme-light:shadow-neu-sm">
      {color && <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />}
      <div className="flex flex-col">
        <span className="font-data text-[10px] uppercase tracking-widest text-muted">{level}</span>
        <span className="text-sm text-ink">
          {name} <span className="font-data text-xs text-muted">({count})</span>
        </span>
      </div>
    </div>
  );
}

function CompanyCard({ company }: { company: AlertCompany }) {
  const bearish = company.direction === 'bearish';
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-hairline p-2.5 theme-light:border-transparent theme-light:shadow-neu-sm">
      <span className="font-data text-xs font-semibold text-ink">{company.ticker}</span>
      <span className="truncate font-editorial text-sm text-ink">{company.name}</span>
      <span className={`font-data text-xs ${bearish ? 'text-bearish' : 'text-bullish'}`}>
        <span aria-hidden="true">{bearish ? '▼' : '▲'}</span> {company.confidence_score}%
      </span>
    </div>
  );
}

function SectorBlock({ sector }: { sector: CompanyGroup }) {
  return (
    <div className="flex w-full flex-col items-center gap-3">
      <LevelHeader level="Level 1 · Direct Impact" name={sector.label} count={sector.companies.length} color={sector.color} />
      <Connector />
      <p className="font-data text-[10px] uppercase tracking-widest text-muted">Level 2 · Companies</p>
      <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {sector.companies.map((c) => (
          <CompanyCard key={c.company_id} company={c} />
        ))}
      </div>
    </div>
  );
}

function SubSectorBlock({ subSector }: { subSector: SubSectorGroup }) {
  return (
    <div className="flex w-full flex-col items-center gap-3">
      <LevelHeader level="Level 3 · Indirect Ripple" name={subSector.label} count={subSector.companies.length} />
      <Connector />
      <p className="font-data text-[10px] uppercase tracking-widest text-muted">Level 4 · Companies</p>
      <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {subSector.companies.map((c) => (
          <CompanyCard key={c.company_id} company={c} />
        ))}
      </div>
    </div>
  );
}

export default function ImpactTree({
  companies,
  article,
  alertCreatedAt,
}: {
  companies: AlertCompany[];
  article: AlertArticle;
  alertCreatedAt: string;
}) {
  const direct = companies.filter((c) => impactLevelKey(c) === 'direct');
  const sectorGroups = groupBySector(direct);
  const subSectorGroups = groupIndirectBySubSector(companies);

  return (
    <ChartCardShell
      number={1}
      title="Multi-Level Impact Tree"
      description="Sectors and companies affected, from direct impact down to indirect ripple effects"
    >
      <div className="flex flex-col items-center gap-4 p-4">
        <NewsNode article={article} alertCreatedAt={alertCreatedAt} />
        <Connector />
        {sectorGroups.length === 0 ? (
          <EmptyLevelNote text="No direct impact identified." />
        ) : (
          <div className="flex w-full flex-col gap-6">
            {sectorGroups.map((sector) => (
              <SectorBlock key={sector.key} sector={sector} />
            ))}
          </div>
        )}
        <div className="w-full border-t border-hairline" />
        {subSectorGroups.length === 0 ? (
          <EmptyLevelNote text="No indirect ripple effects identified." />
        ) : (
          <div className="flex w-full flex-col gap-6">
            {subSectorGroups.map((subSector) => (
              <SubSectorBlock key={subSector.key} subSector={subSector} />
            ))}
          </div>
        )}
      </div>
    </ChartCardShell>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/ImpactTree.test.tsx`
Expected: PASS (all 6 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/ImpactTree.tsx frontend/src/features/visualize/charts/ImpactTree.test.tsx
git commit -m "feat: add ImpactTree multi-level impact tree chart component"
```

---

### Task 3: Wire `ImpactTree` into `AlertChartsPage`

**Files:**
- Modify: `frontend/src/pages/AlertChartsPage.tsx`

**Interfaces:**
- Consumes: `ImpactTree` from Task 2 (`../features/visualize/charts/ImpactTree`), `alert.companies`/`alert.article`/`alert.created_at` (all already present on the `Alert` type this file already fetches).

- [ ] **Step 1: Add the import**

In `frontend/src/pages/AlertChartsPage.tsx`, after line 7 (`import { impactLevelKey } from '../features/visualize/impactLevels';`), add:

```tsx
import ImpactTree from '../features/visualize/charts/ImpactTree';
```

- [ ] **Step 2: Replace the disabled block and blank trailing div**

Find this exact block (lines 240-286 of the current file — the commented-out JSX plus the trailing blank div):

```tsx
      {/* --- Chart system disabled: blank slate, chart rebuild pending ---
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
      --- end disabled chart system --- */}
      <div className="flex-1" />
```

Replace it with:

```tsx
      <div className="flex-1 overflow-y-auto">
        <ImpactTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} />
      </div>
```

Note: `ImpactTree` always receives the full `alert.companies` list (not the breadth-filtered `visibleCompanies`) — the tree always shows both the direct (Level 1/2) and indirect (Level 3/4) sections regardless of the Normal/Drilldown toggle above it, which only affects `StatBar`.

Leave the top-of-file disabled import block (lines 9-34, the `CHARTS` array and future chart imports) and the disabled `expandAll`/`collapseAll`/`index`/`forceCollapse` state block (lines 155-171, 188-193, 202-204, 213-215) untouched — those are scaffolding for charts 2+ and the pager, not part of this task.

- [ ] **Step 3: Typecheck the frontend**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Run the full frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: all tests pass, including the new `transforms.test.ts` and `ImpactTree.test.tsx` cases.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AlertChartsPage.tsx
git commit -m "feat: render ImpactTree chart on AlertChartsPage"
```

---

### Task 4: Manual verification against real data

**Files:** none (verification only; fix forward in this task if something looks wrong).

- [ ] **Step 1: Find a real alert with both direct and indirect companies**

From `backend/`, run:

```bash
.venv/Scripts/python.exe -c "
from app.db import SessionLocal
from app.models import Alert, AlertCompany
db = SessionLocal()
rows = db.query(AlertCompany.alert_id, AlertCompany.impact_level).all()
from collections import defaultdict
levels = defaultdict(set)
for alert_id, level in rows:
    levels[alert_id].add(level or 'direct')
candidates = [aid for aid, ls in levels.items() if 'direct' in ls and ({'indirect_l1', 'indirect_l2'} & ls)]
print(candidates[:5])
"
```

Note one alert id from the printed list (or, if empty, the highest `alert_id` that has any indirect company at all, plus separately any alert id with only direct companies, to cover the empty-Level-3/4 case in the same manual pass).

- [ ] **Step 2: Start both dev servers**

```bash
cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

In a second terminal:

```bash
cd frontend && npm run dev
```

- [ ] **Step 3: Visually check the chart**

Open `http://localhost:5173/alerts/<id>/charts` for the alert id found in Step 1. Confirm:
- News node shows the real article title.
- Level 1/2 shows real sector name(s) and real company tickers/names for direct-impact companies, with correct ▲/▼ glyph and `confidence_score`% matching what `StatBar` above it reports.
- Level 3/4 shows real sub-sector name(s) (or "Unclassified") and real indirect companies.
- Repeat for the direct-only alert id from Step 1 — confirm Level 3/4 shows the "No indirect ripple effects identified." note instead of an empty section.
- Toggle the app's light/dark theme (existing theme switcher) and confirm hairlines, text, and bullish/bearish colors all render correctly in both.

- [ ] **Step 4: Fix forward if needed, then commit**

If anything looks wrong, fix it in the relevant Task 1-3 file and re-run that task's tests before committing:

```bash
git add -A
git commit -m "fix: address manual verification findings in impact tree chart"
```

(Skip this step entirely if nothing needed fixing.)

---

### Task 5: Per-group "why" explanation (added post-manual-verification, per user request)

User asked for an explanation of *why* each affected sector / sub-sector is
impacted, not just the list of companies. There is no sector-level rationale
field in the schema — only per-company `rationale`. This task shows the
highest-confidence company's real `rationale` in each sector/sub-sector
group as that group's explanation (real data, not fabricated) — the
existing `rankByConfidence` transform already ranks a company list by
`confidence_score` descending.

**Files:**
- Modify: `frontend/src/features/visualize/charts/ImpactTree.tsx`
- Modify: `frontend/src/features/visualize/charts/ImpactTree.test.tsx`

**Interfaces:**
- Consumes: `rankByConfidence` (already exported from `../transforms`, used elsewhere in the app e.g. `SectorTree`-adjacent code).
- Produces: no new exports — `SectorBlock`/`SubSectorBlock` render an extra "Why" line each.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/features/visualize/charts/ImpactTree.test.tsx` (inside the existing `describe('ImpactTree', ...)` block):

```tsx
  it('shows the highest-confidence company\'s rationale as the sector\'s explanation', () => {
    render(
      <ImpactTree
        companies={[
          company({ company_id: 1, impact_level: 'direct', sector: 'banking', confidence_score: 40, rationale: 'Lower rationale.' }),
          company({ company_id: 2, impact_level: 'direct', sector: 'banking', confidence_score: 90, rationale: 'Rate cut directly compresses net interest margins.' }),
        ]}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('Rate cut directly compresses net interest margins.')).toBeInTheDocument();
    expect(screen.queryByText('Lower rationale.')).not.toBeInTheDocument();
  });

  it('shows the highest-confidence company\'s rationale as the sub-sector\'s explanation', () => {
    render(
      <ImpactTree
        companies={[
          company({
            company_id: 1,
            impact_level: 'indirect_l1',
            sub_sector: 'nbfc',
            confidence_score: 70,
            rationale: 'NBFCs face higher funding costs as rates rise.',
          }),
        ]}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('NBFCs face higher funding costs as rates rise.')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/ImpactTree.test.tsx`
Expected: FAIL — the new rationale text is not rendered anywhere yet.

- [ ] **Step 3: Implement the "why" line**

In `frontend/src/features/visualize/charts/ImpactTree.tsx`:

1. Update the transforms import to add `rankByConfidence`:

```tsx
import { groupBySector, groupIndirectBySubSector, rankByConfidence, type CompanyGroup, type SubSectorGroup } from '../transforms';
```

2. Add this helper near the top of the file, after the imports (mirrors `InsightCard.tsx`'s existing private `truncatedRationale` — same convention, kept local to this file since it's a 5-line pure function, not worth a cross-file extraction for one duplicate):

```tsx
function truncatedRationale(rationale: string): string {
  const firstSentence = rationale.split(/(?<=[.!?])\s+/)[0];
  if (firstSentence.length <= 160) return firstSentence;
  return `${firstSentence.slice(0, 157)}…`;
}

function WhyExplanation({ companies }: { companies: AlertCompany[] }) {
  const top = rankByConfidence(companies)[0];
  return (
    <div className="flex max-w-md flex-col items-center gap-1 px-2 text-center">
      <span className="font-data text-[10px] uppercase tracking-widest text-muted">Why</span>
      <p className="font-editorial text-sm text-ink">{truncatedRationale(top.rationale)}</p>
    </div>
  );
}
```

3. In `SectorBlock`, add `<WhyExplanation companies={sector.companies} />` directly after the `<LevelHeader ... />` line and before `<Connector />`.

4. In `SubSectorBlock`, add `<WhyExplanation companies={subSector.companies} />` directly after the `<LevelHeader ... />` line and before `<Connector />`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/ImpactTree.test.tsx`
Expected: PASS (all 8 tests — the original 6 plus these 2).

- [ ] **Step 5: Run the full frontend suite and typecheck**

Run: `cd frontend && npx tsc --noEmit && npm test -- --run`
Expected: no type errors, all tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/visualize/charts/ImpactTree.tsx frontend/src/features/visualize/charts/ImpactTree.test.tsx
git commit -m "feat: show highest-confidence company's rationale as each sector/sub-sector's why-explanation"
```
