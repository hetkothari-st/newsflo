# Visualize v2: Inline Company-List Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `reactflow` canvas-based Visualize modal with a "Group by: Tier / Impact / Sector" selector on the existing `AlertCompanies` company list — same `CompanyChip` rows, no canvas, automatically theme-correct.

**Architecture:** `frontend/src/features/visualize/transforms.ts` is rewritten to export three pure grouping functions (`groupByTier`, `groupByImpact`, `groupBySector`) sharing one `CompanyGroup` shape, replacing the old react-flow-shaped tree builders. `AlertCompanies.tsx` gains a `groupMode` state driving which function groups its already-rendered `CompanyChip` rows, replacing the "Visualize →" button. All canvas-specific files (`TreeCanvas`, `TreeView`, `treeLayout`, `tree.ts`, `VisualizeModal`, `ViewPicker`) and the `reactflow` dependency are deleted.

**Tech Stack:** React 18 + TypeScript + Vite + Tailwind (existing, no new dependencies — this plan only removes one).

## Global Constraints

- No fabricated precision: `basis` (`direct_mention` | `sector_inference`) is the only signal used for visual weight (opacity), never `magnitude_low`/`magnitude_high` — this project has an explicit prior rule against showing/implying magnitude precision (see `frontend/src/components/ReasoningPanel.tsx`'s `precedentLine` comment).
- All colors flow through the app's existing CSS-variable tokens (`text-ink`, `text-muted`, `text-bullish`, `text-bearish`) or the existing `sectorColor()` swatch-dot convention — no hardcoded hex for any full-background or full-row color. Small identity dots (sector color) may stay fixed hex, matching `CategorySwatch`/`CompanyChip`'s existing avatar-color convention.
- `groupByImpact` excludes companies whose `direction` is neither exactly `'bullish'` nor `'bearish'` (never fabricate a "neutral" bucket) — same behavior as the old `buildImpactTree`.
- `groupBySector` groups missing/blank/whitespace-only sector under `'Other'` and sorts groups alphabetically — same behavior as the old `buildSectorTree`.
- An empty group (zero companies) is never included in any grouping's output.
- This work happens in the isolated worktree at `C:\Users\ST269\Desktop\newsflo\.claude\worktrees\visualize-graphs-v2` (branch `worktree-visualize-graphs-v2`), created to avoid colliding with other concurrent sessions actively committing to `master` right now.
- `CompanyChip.tsx` itself is not modified — the basis-driven opacity is applied by a wrapping `<div>` in `AlertCompanies.tsx`, keeping this change isolated from that shared, widely-used component.

---

### Task 1: Rewrite `transforms.ts` — `groupByTier`/`groupByImpact`/`groupBySector`

**Files:**
- Modify: `frontend/src/features/visualize/transforms.ts` (full rewrite)
- Modify: `frontend/src/features/visualize/transforms.test.ts` (full rewrite)

**Interfaces:**
- Consumes: `AlertCompany` from `frontend/src/lib/api.ts`, `sectorColor` from `./colors.ts` (both unchanged)
- Produces: `CompanyGroup` interface (`{ key: string; label: string; color?: string; companies: AlertCompany[] }`), `groupByTier(companies: AlertCompany[]): CompanyGroup[]`, `groupByImpact(companies: AlertCompany[]): CompanyGroup[]`, `groupBySector(companies: AlertCompany[]): CompanyGroup[]` — consumed by `AlertCompanies.tsx` in Task 2.

- [ ] **Step 1: Write the failing test**

Replace the full contents of `frontend/src/features/visualize/transforms.test.ts` with:

```ts
import { describe, expect, it } from 'vitest';
import { groupByTier, groupByImpact, groupBySector } from './transforms';
import type { AlertCompany } from '../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('groupByTier', () => {
  it('orders groups Nifty 50 -> Next 50 -> Midcap 150 -> Smallcap 250 -> Global -> Other', () => {
    const groups = groupByTier([
      company({ company_id: 1, index_tier: 'OTHER' }),
      company({ company_id: 2, index_tier: 'GLOBAL_LARGE_CAP' }),
      company({ company_id: 3, index_tier: 'NIFTY50' }),
      company({ company_id: 4, index_tier: 'NIFTYNEXT50' }),
      company({ company_id: 5, index_tier: 'NIFTYMIDCAP150' }),
      company({ company_id: 6, index_tier: 'NIFTYSMALLCAP250' }),
    ]);
    expect(groups.map((g) => g.label)).toEqual([
      'Nifty 50', 'Nifty Next 50', 'Nifty Midcap 150', 'Nifty Smallcap 250', 'Global', 'Other',
    ]);
  });

  it('falls back unrecognized tiers to Other', () => {
    const groups = groupByTier([company({ index_tier: 'SMALLCAP' })]);
    expect(groups.map((g) => g.label)).toEqual(['Other']);
  });

  it('omits a tier group with zero companies', () => {
    const groups = groupByTier([company({ index_tier: 'NIFTY50' })]);
    expect(groups.map((g) => g.label)).toEqual(['Nifty 50']);
  });
});

describe('groupByImpact', () => {
  it('splits companies into Bullish and Bearish groups', () => {
    const groups = groupByImpact([
      company({ company_id: 1, direction: 'bullish' }),
      company({ company_id: 2, direction: 'bearish' }),
    ]);
    expect(groups.map((g) => g.label)).toEqual(['Bullish', 'Bearish']);
    expect(groups[0].companies).toHaveLength(1);
    expect(groups[1].companies).toHaveLength(1);
  });

  it('omits a group with zero companies rather than rendering it empty', () => {
    const groups = groupByImpact([company({ direction: 'bullish' })]);
    expect(groups.map((g) => g.label)).toEqual(['Bullish']);
  });

  it('excludes companies whose direction is neither bullish nor bearish', () => {
    const groups = groupByImpact([company({ direction: 'unknown' })]);
    expect(groups).toHaveLength(0);
  });

  it('excludes an unrecognized-direction company while still bucketing its bullish/bearish siblings', () => {
    const groups = groupByImpact([
      company({ company_id: 1, direction: 'bullish' }),
      company({ company_id: 2, direction: 'bearish' }),
      company({ company_id: 3, direction: 'unknown' }),
    ]);
    const bullish = groups.find((g) => g.label === 'Bullish');
    const bearish = groups.find((g) => g.label === 'Bearish');
    expect(bullish?.companies).toHaveLength(1);
    expect(bearish?.companies).toHaveLength(1);
    expect(groups).toHaveLength(2);
  });
});

describe('groupBySector', () => {
  it('groups companies by sector, alphabetically', () => {
    const groups = groupBySector([
      company({ company_id: 1, sector: 'Financials' }),
      company({ company_id: 2, sector: 'Energy' }),
      company({ company_id: 3, sector: 'Energy' }),
    ]);
    expect(groups.map((g) => g.label)).toEqual(['Energy', 'Financials']);
    expect(groups[0].companies).toHaveLength(2);
  });

  it('groups companies with no sector under "Other"', () => {
    const groups = groupBySector([company({ sector: undefined })]);
    expect(groups.map((g) => g.label)).toEqual(['Other']);
  });

  it('groups companies with an empty or whitespace-only sector under "Other"', () => {
    const groups = groupBySector([
      company({ company_id: 1, sector: '' }),
      company({ company_id: 2, sector: '   ' }),
    ]);
    expect(groups.map((g) => g.label)).toEqual(['Other']);
    expect(groups[0].companies).toHaveLength(2);
  });

  it('assigns each sector group a deterministic color', () => {
    const groups = groupBySector([company({ sector: 'Energy' })]);
    expect(groups[0].color).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/features/visualize/transforms.test.ts`
Expected: FAIL — `groupByTier`/`groupByImpact`/`groupBySector` are not exported by `transforms.ts` yet (it still exports `buildImpactTree`/`buildSectorTree`)

- [ ] **Step 3: Implement**

Replace the full contents of `frontend/src/features/visualize/transforms.ts` with:

```ts
import type { AlertCompany } from '../../lib/api';
import { sectorColor } from './colors';

export interface CompanyGroup {
  key: string;
  label: string;
  color?: string;
  companies: AlertCompany[];
}

const TIER_ORDER = [
  'NIFTY50',
  'NIFTYNEXT50',
  'NIFTYMIDCAP150',
  'NIFTYSMALLCAP250',
  'GLOBAL_LARGE_CAP',
  'OTHER',
] as const;
const TIER_LABEL: Record<string, string> = {
  NIFTY50: 'Nifty 50',
  NIFTYNEXT50: 'Nifty Next 50',
  NIFTYMIDCAP150: 'Nifty Midcap 150',
  NIFTYSMALLCAP250: 'Nifty Smallcap 250',
  GLOBAL_LARGE_CAP: 'Global',
  OTHER: 'Other',
};

function tierKey(company: AlertCompany): string {
  return TIER_LABEL[company.index_tier] ? company.index_tier : 'OTHER';
}

export function groupByTier(companies: AlertCompany[]): CompanyGroup[] {
  return TIER_ORDER.map((tier) => ({
    key: tier,
    label: TIER_LABEL[tier],
    companies: companies.filter((c) => tierKey(c) === tier),
  })).filter((g) => g.companies.length > 0);
}

export function groupByImpact(companies: AlertCompany[]): CompanyGroup[] {
  const bullish = companies.filter((c) => c.direction === 'bullish');
  const bearish = companies.filter((c) => c.direction === 'bearish');

  const groups: CompanyGroup[] = [];
  if (bullish.length > 0) groups.push({ key: 'bullish', label: 'Bullish', companies: bullish });
  if (bearish.length > 0) groups.push({ key: 'bearish', label: 'Bearish', companies: bearish });
  return groups;
}

export function groupBySector(companies: AlertCompany[]): CompanyGroup[] {
  const bySector = new Map<string, AlertCompany[]>();
  for (const company of companies) {
    const sector = company.sector && company.sector.trim().length > 0 ? company.sector : 'Other';
    const group = bySector.get(sector) ?? [];
    group.push(company);
    bySector.set(sector, group);
  }

  return [...bySector.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([sector, group]) => ({ key: sector, label: sector, color: sectorColor(sector), companies: group }));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/features/visualize/transforms.test.ts`
Expected: `11 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/transforms.ts frontend/src/features/visualize/transforms.test.ts
git commit -m "refactor: replace react-flow tree builders with plain groupByTier/Impact/Sector"
```

---

### Task 2: Rewrite `AlertCompanies.tsx` — Group-by selector, replacing the Visualize button

**Files:**
- Modify: `frontend/src/components/AlertCompanies.tsx` (full rewrite)
- Modify: `frontend/src/components/AlertCompanies.test.tsx` (remove 2 Visualize-modal tests, add 3 new tests, keep the other 4 tests unchanged)

**Interfaces:**
- Consumes: `groupByTier`, `groupByImpact`, `groupBySector`, `CompanyGroup` from `../features/visualize/transforms` (Task 1)
- No change to `AlertCompanies`'s own exported signature (`{ alert: Alert; isAuthenticated: boolean }`) — `Feed.tsx`'s usage is unaffected.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `frontend/src/components/AlertCompanies.test.tsx` with:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import AlertCompanies from './AlertCompanies';
import type { Alert } from '../lib/api';

const alert: Alert = {
  id: 1,
  category: 'oil_energy',
  created_at: '2026-07-09T10:00:00+00:00',
  article: { id: 1, title: 'US strikes Iran oil export sites', url: 'https://example.com/a', image_url: null },
  companies: [
    {
      company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance Industries', index_tier: 'NIFTY50',
      direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'Refiner up.', key_points: [],
      basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN', in_my_holdings: true, past_mentions: [],
      sector: 'Energy',
    },
    {
      company_id: 2, ticker: 'ONGC.NS', name: 'ONGC', index_tier: 'NIFTYNEXT50',
      direction: 'bearish', magnitude_low: -3, magnitude_high: -1, rationale: 'Cost pressure.', key_points: [],
      basis: 'sector_inference', confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
      sector: 'Financials',
    },
  ],
};

describe('AlertCompanies', () => {
  it('shows Predicted companies grouped by tier by default', () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    expect(screen.getByText('Nifty 50')).toBeInTheDocument();
    expect(screen.getByText('Nifty Next 50')).toBeInTheDocument();
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.getByText('ONGC')).toBeInTheDocument();
  });

  it('filters to held companies on the My Portfolio tab', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    await userEvent.click(screen.getByRole('button', { name: /my portfolio/i }));
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.queryByText('ONGC')).not.toBeInTheDocument();
  });

  it('shows a login prompt on My Portfolio when logged out with no matches', async () => {
    const anon: Alert = { ...alert, companies: alert.companies.map((c) => ({ ...c, in_my_holdings: false })) };
    render(<AlertCompanies alert={anon} isAuthenticated={false} />);
    await userEvent.click(screen.getByRole('button', { name: /my portfolio/i }));
    expect(screen.getByText(/log in to see holdings-matched alerts/i)).toBeInTheDocument();
  });

  it('renders tier headings in Nifty 50 -> Next 50 -> Midcap 150 -> Smallcap 250 -> Global -> Other order', async () => {
    const tierAlert: Alert = {
      ...alert,
      companies: [
        { ...alert.companies[1], company_id: 1, name: 'Other Co', index_tier: 'OTHER' },
        { ...alert.companies[1], company_id: 2, name: 'Global Co', index_tier: 'GLOBAL_LARGE_CAP' },
        { ...alert.companies[0], company_id: 3, name: 'Fifty Co', index_tier: 'NIFTY50' },
        { ...alert.companies[1], company_id: 4, name: 'Next Fifty Co', index_tier: 'NIFTYNEXT50' },
        { ...alert.companies[1], company_id: 5, name: 'Midcap Co', index_tier: 'NIFTYMIDCAP150' },
        { ...alert.companies[1], company_id: 6, name: 'Smallcap Co', index_tier: 'NIFTYSMALLCAP250' },
      ],
    };
    render(<AlertCompanies alert={tierAlert} isAuthenticated />);
    const headings = screen.getAllByText(
      /^(Nifty 50|Nifty Next 50|Nifty Midcap 150|Nifty Smallcap 250|Global|Other)$/,
    );
    expect(headings.map((el) => el.textContent)).toEqual([
      'Nifty 50', 'Nifty Next 50', 'Nifty Midcap 150', 'Nifty Smallcap 250', 'Global', 'Other',
    ]);
  });

  it('shows Bullish/Bearish group headers with counts when grouped by Impact', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'impact');
    expect(screen.getByText('Bullish · 1')).toBeInTheDocument();
    expect(screen.getByText('Bearish · 1')).toBeInTheDocument();
  });

  it('shows sector group headers with counts when grouped by Sector', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'sector');
    expect(screen.getByText('Energy · 1')).toBeInTheDocument();
    expect(screen.getByText('Financials · 1')).toBeInTheDocument();
  });

  it('mutes sector-inferred companies relative to direct-mention companies when grouped', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'impact');
    expect(screen.getByText('Reliance Industries').closest('.opacity-70')).toBeNull();
    expect(screen.getByText('ONGC').closest('.opacity-70')).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/components/AlertCompanies.test.tsx`
Expected: FAIL — no `combobox` role exists yet (no `<select>`), and `'Bullish · 1'`/`'Energy · 1'` text doesn't exist

- [ ] **Step 3: Implement**

Replace the full contents of `frontend/src/components/AlertCompanies.tsx` with:

```tsx
import { useState } from 'react';
import type { Alert, AlertCompany } from '../lib/api';
import CompanyChip from './CompanyChip';
import { groupByTier, groupByImpact, groupBySector, type CompanyGroup } from '../features/visualize/transforms';

type Tab = 'predicted' | 'my_demat';
type GroupMode = 'tier' | 'impact' | 'sector';

const GROUP_MODES: GroupMode[] = ['tier', 'impact', 'sector'];
const GROUP_LABEL: Record<GroupMode, string> = {
  tier: 'Tier',
  impact: 'Impact',
  sector: 'Sector',
};

function groupCompanies(mode: GroupMode, companies: AlertCompany[]): CompanyGroup[] {
  if (mode === 'impact') return groupByImpact(companies);
  if (mode === 'sector') return groupBySector(companies);
  return groupByTier(companies);
}

function headerClass(mode: GroupMode, group: CompanyGroup): string {
  if (mode === 'impact') return group.key === 'bullish' ? 'text-bullish' : 'text-bearish';
  return 'text-muted';
}

export default function AlertCompanies({
  alert,
  isAuthenticated,
}: {
  alert: Alert;
  isAuthenticated: boolean;
}) {
  const [tab, setTab] = useState<Tab>('predicted');
  const [groupMode, setGroupMode] = useState<GroupMode>('tier');

  const visible = tab === 'predicted' ? alert.companies : alert.companies.filter((c) => c.in_my_holdings);
  const grouped = groupCompanies(groupMode, visible);

  const tabClass = (active: boolean) =>
    `pb-1 text-xs uppercase tracking-widest border-b-2 ${
      active ? 'border-ink text-ink' : 'border-transparent text-muted'
    }`;

  const emptyCopy =
    tab === 'my_demat'
      ? isAuthenticated
        ? 'None of your holdings are affected by this story.'
        : 'Log in to see holdings-matched alerts.'
      : 'No affected companies for this story.';

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <div className="flex gap-4">
          <button type="button" onClick={() => setTab('predicted')} className={tabClass(tab === 'predicted')}>
            Predicted
          </button>
          <button type="button" onClick={() => setTab('my_demat')} className={tabClass(tab === 'my_demat')}>
            My Portfolio
          </button>
        </div>
        <label className="flex items-center gap-1.5 text-xs uppercase tracking-widest text-muted">
          Group
          <select
            value={groupMode}
            onChange={(e) => setGroupMode(e.target.value as GroupMode)}
            className="rounded-md border border-hairline bg-surface px-1.5 py-0.5 text-xs text-ink theme-light:border-transparent theme-light:shadow-neu-sm"
          >
            {GROUP_MODES.map((mode) => (
              <option key={mode} value={mode}>
                {GROUP_LABEL[mode]}
              </option>
            ))}
          </select>
        </label>
      </div>
      {visible.length === 0 ? (
        <p className="text-xs text-muted">{emptyCopy}</p>
      ) : (
        grouped.map((group) => (
          <div key={group.key} className="flex flex-col gap-2">
            <p className={`flex items-center gap-1.5 text-xs uppercase tracking-widest ${headerClass(groupMode, group)}`}>
              {group.color && (
                <span aria-hidden="true" className="h-2 w-2 rounded-full" style={{ backgroundColor: group.color }} />
              )}
              {groupMode === 'tier' ? group.label : `${group.label} · ${group.companies.length}`}
            </p>
            <div className="grid grid-cols-1 items-start gap-2 sm:grid-cols-2">
              {group.companies.map((company) => (
                <div
                  key={company.company_id}
                  className={groupMode !== 'tier' && company.basis === 'sector_inference' ? 'opacity-70' : undefined}
                >
                  <CompanyChip company={company} />
                </div>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/AlertCompanies.test.tsx`
Expected: `7 passed`

- [ ] **Step 5: Confirm the only remaining tsc error is the known, expected one**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: exactly one error, from `frontend/src/features/visualize/VisualizeModal.tsx`, of the form `Module '"./transforms"' has no exported member 'buildImpactTree'` (and the same for `buildSectorTree`). This is expected and correct at this point: `VisualizeModal.tsx` is still the only file importing the old tree-builder names, and it is deleted in Task 3, Step 1. `AlertCompanies.tsx` and `AlertCompanies.test.tsx` themselves must show NO errors — if tsc reports any error outside `VisualizeModal.tsx`, that is a real problem to fix before continuing (e.g. `TreeView.tsx`/`ViewPicker.tsx` also import from `transforms.ts` and would need the same "expected until Task 3" treatment — if you see errors from those too, that's still fine as long as every reported error is confined to files being deleted in Task 3, Step 1, and none of them are `AlertCompanies.tsx`/`AlertCompanies.test.tsx`).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/AlertCompanies.tsx frontend/src/components/AlertCompanies.test.tsx
git commit -m "feat: replace Visualize button with inline Group-by (Tier/Impact/Sector) selector"
```

---

### Task 3: Delete the canvas-based visualize feature and the `reactflow` dependency

**Files:**
- Delete: `frontend/src/features/visualize/TreeCanvas.tsx`, `frontend/src/features/visualize/TreeCanvas.test.tsx`
- Delete: `frontend/src/features/visualize/TreeView.tsx`, `frontend/src/features/visualize/TreeView.test.tsx`
- Delete: `frontend/src/features/visualize/treeLayout.ts`, `frontend/src/features/visualize/treeLayout.test.ts`
- Delete: `frontend/src/features/visualize/tree.ts`
- Delete: `frontend/src/features/visualize/VisualizeModal.tsx`, `frontend/src/features/visualize/VisualizeModal.test.tsx`
- Delete: `frontend/src/features/visualize/ViewPicker.tsx`, `frontend/src/features/visualize/ViewPicker.test.tsx`
- Modify: `frontend/package.json`, `frontend/package-lock.json` (remove `reactflow`, via `npm uninstall`)
- Modify: `frontend/src/test/setup.ts` (remove the ResizeObserver polyfill block only — keep the `@testing-library/jest-dom` import and the `Element.prototype.scrollTo`/`window.scrollTo` polyfill block added independently by another session)

**Interfaces:** None — this task only removes now-unused code. `colors.ts` (`sectorColor`) and `transforms.ts` (Task 1) are NOT touched — they're still used.

- [ ] **Step 1: Delete the canvas-specific files**

```bash
git rm frontend/src/features/visualize/TreeCanvas.tsx frontend/src/features/visualize/TreeCanvas.test.tsx
git rm frontend/src/features/visualize/TreeView.tsx frontend/src/features/visualize/TreeView.test.tsx
git rm frontend/src/features/visualize/treeLayout.ts frontend/src/features/visualize/treeLayout.test.ts
git rm frontend/src/features/visualize/tree.ts
git rm frontend/src/features/visualize/VisualizeModal.tsx frontend/src/features/visualize/VisualizeModal.test.tsx
git rm frontend/src/features/visualize/ViewPicker.tsx frontend/src/features/visualize/ViewPicker.test.tsx
```

- [ ] **Step 2: Remove the `reactflow` dependency**

Run (from `frontend/`): `npm uninstall reactflow`
Expected: `package.json`'s `reactflow` entry is removed; `package-lock.json` updates.

- [ ] **Step 3: Read the current `frontend/src/test/setup.ts` and remove only the ResizeObserver block**

Read the file first (it currently has three blocks: the `jest-dom` import, the ResizeObserver polyfill, and a `scrollTo`/`window.scrollTo` polyfill added independently by another session). Remove ONLY the ResizeObserver block — its comment explicitly says it exists for react-flow, which no longer exists in this codebase. The file should end up as:

```ts
import '@testing-library/jest-dom';

// jsdom doesn't implement real scrolling: Element.prototype.scrollTo is
// undefined, and window.scrollTo exists but throws "Not implemented" when
// called. Several components (e.g. Feed's "N new" reveal) call these, so
// stub no-ops globally -- individual tests can still override them with
// their own spy/mock to assert on call args.
Element.prototype.scrollTo = function scrollTo() {};
window.scrollTo = function scrollTo() {};
```

If the live file's `scrollTo` block differs even slightly from the text above (e.g. different comment wording), preserve the live file's actual `scrollTo` block verbatim — only delete the ResizeObserver block, do not rewrite anything else in this file.

- [ ] **Step 4: Verify the full frontend suite**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: no errors

Run: `npm test`
Expected: all test files pass, 0 failures. Report the exact file/test counts in your report — do not assume a number, count from the actual output (this task removes 5 test files' worth of tests from the Task-2-baseline count, so the total will be lower than before this task, not higher).

- [ ] **Step 5: Commit**

```bash
git add -A frontend/
git commit -m "chore: remove reactflow dependency and the canvas-based visualize feature"
```

---

## Final verification (after all tasks)

- [ ] Run the full frontend suite: `npx tsc --noEmit && npm test` from `frontend/` — expect all passing, 0 failures.
- [ ] Confirm `frontend/package.json` no longer lists `reactflow` under `dependencies`.
- [ ] Confirm `frontend/src/features/visualize/` contains only `colors.ts`, `colors.test.ts`, `transforms.ts`, `transforms.test.ts`.
- [ ] Manually smoke-test: `npm run dev` (frontend) against a running backend, open a feed alert with 2+ companies across different sectors and directions, confirm the "Group" selector switches between Tier/Impact/Sector, confirm sector-inferred companies render visibly muted relative to direct-mention ones, confirm it looks correct in both light and dark theme (use the app's theme toggle).
