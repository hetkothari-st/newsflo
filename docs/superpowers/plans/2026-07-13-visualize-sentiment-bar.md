# Sentiment Proportion Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real visual element (a Bullish/Bearish proportion bar) to `AlertCompanies.tsx`, since the v2 grouping redesign shipped as a text-only list with no chart/graphic at all, which the user flagged as missing after seeing it live.

**Architecture:** New presentational component `frontend/src/features/visualize/SentimentBar.tsx` — a pure function of `AlertCompany[]`, no state. Computes bullish/bearish counts (excluding unrecognized directions, same no-fabrication rule as `groupByImpact`), renders a single two-segment horizontal bar (width proportional to count) plus a direct-label line ("N Bullish · M Bearish"). Wired into `AlertCompanies.tsx` above the grouped list, computed from `visible` (the already tab-filtered company list) so it reflects the active Predicted/My Portfolio selection.

**Tech Stack:** React 18 + TypeScript + Tailwind (existing, no new dependencies).

## Global Constraints (from this conversation's design discussion)

- Count-based only: the bar's segments are proportional to `direction === 'bullish'` / `'bearish'` counts. Never magnitude — this project has a standing rule against implying numeric precision the model doesn't have (see `frontend/src/components/ReasoningPanel.tsx`'s `precedentLine` comment).
- Companies whose `direction` is neither exactly `'bullish'` nor `'bearish'` are excluded from both the bar and its counts (same exclusion rule as `groupByImpact` in `frontend/src/features/visualize/transforms.ts`) — never render a fabricated third segment.
- Colors: `bg-bullish`/`text-bullish`/`bg-bearish`/`text-bearish` (existing theme-aware Tailwind tokens) only — no hardcoded hex.
- Two adjacent fills get a 2px surface-colored gap between them (only when both segments are present) — a small design-system-agnostic mark-spec detail for stacked/adjacent fills, not decorative.
- Direct-label the counts in text (never color-alone) — matches this project's existing convention (e.g. `CompanyChip`'s direction arrow is always paired with company name text, never a bare colored mark).
- If there are zero companies with a recognized direction, render nothing (return `null`) — do not draw an empty or fully-gray bar.
- This work happens in the isolated worktree at `C:\Users\ST269\Desktop\newsflo\.claude\worktrees\visualize-sentiment-bar` (branch `worktree-visualize-sentiment-bar`), to avoid colliding with other concurrent sessions.

---

### Task 1: `SentimentBar` component + `AlertCompanies` wiring

**Files:**
- Create: `frontend/src/features/visualize/SentimentBar.tsx`
- Create: `frontend/src/features/visualize/SentimentBar.test.tsx`
- Modify: `frontend/src/components/AlertCompanies.tsx`
- Modify: `frontend/src/components/AlertCompanies.test.tsx`

**Interfaces:**
- Produces: `<SentimentBar companies={AlertCompany[]} />` — consumed by `AlertCompanies.tsx`.

- [ ] **Step 1: Write the failing test for `SentimentBar`**

Create `frontend/src/features/visualize/SentimentBar.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SentimentBar from './SentimentBar';
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

describe('SentimentBar', () => {
  it('shows direct-labeled bullish and bearish counts', () => {
    render(
      <SentimentBar
        companies={[
          company({ company_id: 1, direction: 'bullish' }),
          company({ company_id: 2, direction: 'bullish' }),
          company({ company_id: 3, direction: 'bearish' }),
        ]}
      />,
    );
    expect(screen.getByText('2 Bullish')).toBeInTheDocument();
    expect(screen.getByText('1 Bearish')).toBeInTheDocument();
  });

  it('excludes companies with an unrecognized direction from the counts', () => {
    render(
      <SentimentBar
        companies={[
          company({ company_id: 1, direction: 'bullish' }),
          company({ company_id: 2, direction: 'unknown' }),
        ]}
      />,
    );
    expect(screen.getByText('1 Bullish')).toBeInTheDocument();
    expect(screen.getByText('0 Bearish')).toBeInTheDocument();
  });

  it('renders nothing when there are no companies with a recognized direction', () => {
    const { container } = render(
      <SentimentBar companies={[company({ direction: 'unknown' })]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<SentimentBar companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/features/visualize/SentimentBar.test.tsx`
Expected: FAIL — `SentimentBar.tsx` does not exist

- [ ] **Step 3: Implement `SentimentBar.tsx`**

Create `frontend/src/features/visualize/SentimentBar.tsx`:

```tsx
import type { AlertCompany } from '../../lib/api';

export default function SentimentBar({ companies }: { companies: AlertCompany[] }) {
  const bullish = companies.filter((c) => c.direction === 'bullish').length;
  const bearish = companies.filter((c) => c.direction === 'bearish').length;
  const total = bullish + bearish;

  if (total === 0) return null;

  const bullishPct = (bullish / total) * 100;
  const bearishPct = (bearish / total) * 100;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex h-2 overflow-hidden rounded-full bg-hairline">
        {bullish > 0 && (
          <div
            className={`bg-bullish ${bearish > 0 ? 'border-r-2 border-page' : ''}`}
            style={{ width: `${bullishPct}%` }}
          />
        )}
        {bearish > 0 && <div className="bg-bearish" style={{ width: `${bearishPct}%` }} />}
      </div>
      <p className="text-xs">
        <span className="text-bullish">{bullish} Bullish</span>
        <span className="text-muted"> · </span>
        <span className="text-bearish">{bearish} Bearish</span>
      </p>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/features/visualize/SentimentBar.test.tsx`
Expected: `4 passed`

- [ ] **Step 5: Write the failing test for `AlertCompanies` wiring**

Add this test to `frontend/src/components/AlertCompanies.test.tsx` (append inside the existing `describe('AlertCompanies', ...)` block, after the last existing `it`):

```tsx
  it('shows the sentiment bar reflecting the currently visible (tab-filtered) companies', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    expect(screen.getByText('1 Bullish')).toBeInTheDocument();
    expect(screen.getByText('1 Bearish')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /my portfolio/i }));
    expect(screen.getByText('1 Bullish')).toBeInTheDocument();
    expect(screen.getByText('0 Bearish')).toBeInTheDocument();
  });
```

(This relies on the existing `alert` fixture already in the file: `Reliance Industries` is `bullish`/`in_my_holdings: true`, `ONGC` is `bearish`/`in_my_holdings: false` — confirm this against the live fixture before running; if the fixture differs, adjust the expected counts to match its actual `direction`/`in_my_holdings` values rather than changing the fixture.)

- [ ] **Step 6: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/components/AlertCompanies.test.tsx`
Expected: FAIL — `'1 Bullish'` text does not exist yet

- [ ] **Step 7: Wire `SentimentBar` into `AlertCompanies.tsx`**

In `frontend/src/components/AlertCompanies.tsx`, add the import alongside the existing imports:

```tsx
import SentimentBar from '../features/visualize/SentimentBar';
```

Add `<SentimentBar companies={visible} />` between the tabs/Group-by row and the grouped-list rendering, so the returned JSX becomes:

```tsx
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
      <SentimentBar companies={visible} />
      {grouped.length === 0 ? (
        <p className="text-xs text-muted">{emptyCopy}</p>
      ) : (
```

(Everything from `{grouped.length === 0 ? (` through the end of the file is unchanged — only the new import line and the new `<SentimentBar companies={visible} />` line are added. Read the live file first to confirm nothing else has drifted since this plan was written.)

- [ ] **Step 8: Run test to verify it passes**

Run: `npx vitest run src/components/AlertCompanies.test.tsx`
Expected: all tests in the file pass (9 total: 8 existing + 1 new)

- [ ] **Step 9: Run the full frontend suite and typecheck**

Run (from `frontend/`): `npx tsc --noEmit && npm test`
Expected: no type errors; all test files pass (32 files, 158 tests: 153 baseline + 4 new `SentimentBar.test.tsx` tests + 1 new `AlertCompanies.test.tsx` test). Report the exact numbers from the actual output rather than trusting this arithmetic — verify, don't assume.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/features/visualize/SentimentBar.tsx frontend/src/features/visualize/SentimentBar.test.tsx frontend/src/components/AlertCompanies.tsx frontend/src/components/AlertCompanies.test.tsx
git commit -m "feat: add Bullish/Bearish sentiment proportion bar to the company list"
```

---

## Final verification

- [ ] Run the full frontend suite: `npx tsc --noEmit && npm test` from `frontend/` — expect all passing, 0 failures, exact counts confirmed from actual output.
- [ ] Manually smoke-test: `npm run dev` against a running backend, open an alert with mixed bullish/bearish companies, confirm the bar renders above the grouped list with correct proportions and counts, confirm it looks correct in both light and dark theme.
