# Measurement-First Impact Architecture — Phase 5 (Intensity Breakdown Popup) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the intensity score's component breakdown reachable everywhere the score appears, per the task brief's compliance rule: *"The score must never appear without a reachable breakdown."* Phase 4 shipped `FeedRowV2` with an intensity bar + score number that render but do nothing when touched — this phase makes them open a popup showing the score, band, per-component `label — raw ×weight` breakdown with mini bars, and the compliance disclaimer line verbatim. Only one intensity surface exists today (the Level 0 feed row); deep-dive and peer-row surfaces (Phases 6/7) will reuse this same popup component when they're built.

**Architecture:** Purely additive to the existing `feed-v2` component tree from Phase 4 — one new presentational component plus a small, precise modification to `FeedRowV2.tsx` (already part of this ongoing build, not one of the "never touch" pre-existing feed files from Phase 4's constraints). No backend changes: `FeedV2Alert.intensity.components` already carries everything this popup needs (shipped in Phase 4). This phase has a UI component, so the task brief's HARD RULE applies again: Playwright screenshots at 390px/1920px, both themes, actually looked at and compared against spec before this phase is done.

**Tech Stack:** Same as Phase 4 — React + TypeScript + Vite + Tailwind, Vitest + Testing Library, Playwright (already installed and configured from Phase 4 — this phase extends the existing `e2e/feed-v2-screenshots.spec.ts`, doesn't reinstall anything).

## Global Constraints

- **Never delete existing code** — this phase modifies `FeedRowV2.tsx` (adding a click handler and rendering the new popup), which is a real, intentional change to already-shipped code from this same ongoing build (not one of Phase 4's protected pre-existing files) — but the change must be additive within that file: the existing row layout, tests, and behavior stay intact, only new interactive behavior is added alongside.
- **The intensity score must never be tappable-looking without actually being tappable, and must never appear anywhere without this breakdown being reachable from it.** After this phase, `FeedRowV2`'s intensity bar/score is the one surface that satisfies this; Phases 6/7 must wire the same popup into their own intensity surfaces when built (out of scope here).
- **Tapping the intensity bar/score must NOT also open the Level 1 summary** (the row's own `onOpen` click handler) — the two are deliberately separate, same discipline this codebase already applies elsewhere (e.g. the (i)-button-vs-deep-dive separation planned for a later phase). Achieved via `stopPropagation` on the intensity tap target AND by rendering the popup as a sibling of the row's clickable wrapper (a `<>...</>` Fragment), never nested inside it — `AlertDetail` is confirmed NOT portaled (a plain `fixed inset-0` div in the normal render tree, `frontend/src/components/AlertDetail.tsx`), so nesting it inside the row's `onClick` wrapper would let a click anywhere in the open popup (including its backdrop, which also has no `stopPropagation`) bubble up and re-trigger the row's `onOpen`.
- **The disclaimer line is verbatim, always present, on every intensity breakdown:** *"Intensity measures how hard the news hit this stock — not whether it's a good investment."* — copied character-for-character, no rewording.
- **The "fundamental note" section (advisory tier only) is deliberately absent from this build.** No `FundamentalEstimate`/advisory data model exists yet (out of scope for this whole task per the original task brief) — the popup component has no prop for it and renders nothing in its place. This is a documented, deliberate gap for a future advisory-tier phase to fill, not an oversight.
- **No LLM-generated number reaches a user** — every number in this popup (`score`, `band`, each component's `raw`/`weight`/`contribution`) comes straight from `compute_intensity` (Phase 2), already serialized by Phase 4's `GET /api/feed-v2`. Nothing new is computed here; this is a pure rendering task.
- Typography/color rules carried forward from Phase 4: numbers `font-data`, prose `font-sans`, page frame `mx-auto w-full max-w-3xl px-4` (already handled by `AlertDetail`'s own panel sizing — this phase's content just needs `rounded-lg bg-surface p-5` section containers with `gap-3` between them, matching `Level1SummaryV2`'s established pattern).
- Full backend test suite (unaffected — no backend changes) and full frontend test suite must both pass with zero regressions at the end.

---

## File Structure

```
frontend/src/components/feed-v2/IntensityBreakdownPopup.tsx       NEW — the breakdown content
frontend/src/components/feed-v2/IntensityBreakdownPopup.test.tsx  NEW
frontend/src/components/feed-v2/FeedRowV2.tsx                      MODIFY — tappable intensity bar/score, opens the popup
frontend/src/components/feed-v2/FeedRowV2.test.tsx                 MODIFY — new tests for the popup interaction

frontend/e2e/feed-v2-screenshots.spec.ts    MODIFY — add 4 new screenshots (popup open, dark/light × mobile/desktop)
```

---

## Task 1: `IntensityBreakdownPopup` — the breakdown content

**Files:**
- Create: `frontend/src/components/feed-v2/IntensityBreakdownPopup.tsx`
- Test: `frontend/src/components/feed-v2/IntensityBreakdownPopup.test.tsx`

**Interfaces:**
- Consumes: `Intensity`/`IntensityComponent` types (`frontend/src/lib/feedV2Api.ts`, shipped in Phase 4), `intensityBandColorClass` (`frontend/src/lib/feedV2Format.ts`, shipped in Phase 4).
- Produces: `<IntensityBreakdownPopup intensity={Intensity} />` — content only (no modal chrome; the caller wraps this in the existing generic `AlertDetail` shell, same pattern as `Level1SummaryV2`).

**Layout (per spec §4.2, §9 and the task brief's Phase 5 section):** large score + band label; then one row per component as `label — raw ×weight` with a mini bar (bar fill = that component's own normalized sub-score, i.e. `contribution / weight`, since `contribution = normalized_subscore * weight`); then, always, the disclaimer line verbatim.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/feed-v2/IntensityBreakdownPopup.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import IntensityBreakdownPopup from './IntensityBreakdownPopup';
import type { Intensity } from '../../lib/feedV2Api';

function makeIntensity(overrides: Partial<Intensity> = {}): Intensity {
  return {
    score: 82,
    band: 'High',
    components: [
      { label: 'excess', raw: -4.2, weight: 0.55, contribution: 55.0 },
      { label: 'volume', raw: 3.1, weight: 0.25, contribution: 25.0 },
      { label: 'breadth', raw: 40, weight: 0.2, contribution: 8.0 },
    ],
    ...overrides,
  };
}

describe('IntensityBreakdownPopup', () => {
  it('renders the large score and band label', () => {
    render(<IntensityBreakdownPopup intensity={makeIntensity()} />);
    expect(screen.getByText('82')).toBeInTheDocument();
    expect(screen.getByText('High')).toBeInTheDocument();
  });

  it('renders one row per component with label, raw, and weight', () => {
    render(<IntensityBreakdownPopup intensity={makeIntensity()} />);
    expect(screen.getByText(/excess/i)).toBeInTheDocument();
    expect(screen.getByText(/-4\.2/)).toBeInTheDocument();
    expect(screen.getByText(/×0\.55/)).toBeInTheDocument();
    expect(screen.getByText(/volume/i)).toBeInTheDocument();
    expect(screen.getByText(/breadth/i)).toBeInTheDocument();
  });

  it('always renders the exact compliance disclaimer', () => {
    render(<IntensityBreakdownPopup intensity={makeIntensity()} />);
    expect(
      screen.getByText(
        "Intensity measures how hard the news hit this stock — not whether it's a good investment.",
      ),
    ).toBeInTheDocument();
  });

  it('renders the disclaimer for every band, not just High', () => {
    const { rerender } = render(<IntensityBreakdownPopup intensity={makeIntensity({ band: 'Low', score: 12 })} />);
    expect(
      screen.getByText(
        "Intensity measures how hard the news hit this stock — not whether it's a good investment.",
      ),
    ).toBeInTheDocument();

    rerender(<IntensityBreakdownPopup intensity={makeIntensity({ band: 'Moderate', score: 55 })} />);
    expect(
      screen.getByText(
        "Intensity measures how hard the news hit this stock — not whether it's a good investment.",
      ),
    ).toBeInTheDocument();
  });

  it('handles a component with zero weight without dividing by zero', () => {
    const intensity = makeIntensity({
      components: [{ label: 'excess', raw: 0, weight: 0, contribution: 0 }],
    });
    render(<IntensityBreakdownPopup intensity={intensity} />);
    expect(screen.getByText(/excess/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/feed-v2/IntensityBreakdownPopup.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/components/feed-v2/IntensityBreakdownPopup.tsx`:

```tsx
import { intensityBandColorClass } from '../../lib/feedV2Format';
import type { Intensity } from '../../lib/feedV2Api';

interface IntensityBreakdownPopupProps {
  intensity: Intensity;
}

// Verbatim per docs/NEWS_IMPACT_APP_SPEC.md §4.2/§7 -- never reword. This is
// a compliance control (intensity is a news-impact metric, never a rating),
// not a style choice.
const DISCLAIMER =
  "Intensity measures how hard the news hit this stock — not whether it's a good investment.";

export default function IntensityBreakdownPopup({ intensity }: IntensityBreakdownPopupProps) {
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg bg-surface p-5">
        <div className="flex items-baseline gap-3">
          <span className="font-data text-4xl font-medium text-ink">{intensity.score}</span>
          <span className="font-sans text-sm text-muted">{intensity.band}</span>
        </div>
      </div>

      <div className="rounded-lg bg-surface p-5">
        <div className="flex flex-col gap-3">
          {intensity.components.map((component) => {
            // contribution = normalized_subscore * weight (see
            // app/market/intensity.py::compute_intensity) -- recover the
            // component's own 0-100 sub-score for the mini bar's fill.
            const subScore = component.weight > 0 ? component.contribution / component.weight : 0;
            return (
              <div key={component.label}>
                <div className="font-sans text-sm text-ink">
                  <span className="capitalize">{component.label}</span>
                  {' — '}
                  <span className="font-data">{component.raw.toFixed(1)}</span>
                  {' ×'}
                  <span className="font-data">{component.weight.toFixed(2)}</span>
                </div>
                <div className="mt-1 h-1 w-full rounded-sm bg-elevated">
                  <div
                    className={`h-full rounded-sm ${intensityBandColorClass(intensity.band)}`}
                    style={{ width: `${subScore}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Fundamental note (advisory tier only) deliberately omitted -- no
          FundamentalEstimate data model exists yet (out of scope for this
          build). A future advisory-tier phase adds a fundamentalNote prop
          and renders it here, between the components and the disclaimer. */}

      <div className="rounded-lg bg-surface p-5">
        <p className="font-sans text-xs text-muted">{DISCLAIMER}</p>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/feed-v2/IntensityBreakdownPopup.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/feed-v2/IntensityBreakdownPopup.tsx frontend/src/components/feed-v2/IntensityBreakdownPopup.test.tsx
git commit -m "feat: add IntensityBreakdownPopup -- score, band, component breakdown, disclaimer"
```

---

## Task 2: Wire the popup into `FeedRowV2`'s intensity bar/score

**Files:**
- Modify: `frontend/src/components/feed-v2/FeedRowV2.tsx`
- Modify: `frontend/src/components/feed-v2/FeedRowV2.test.tsx`

**Interfaces:**
- Consumes: `IntensityBreakdownPopup` (Task 1), the existing generic `AlertDetail` modal shell (`frontend/src/components/AlertDetail.tsx` — imported, never edited).
- Produces: clicking the intensity bar or score number opens the breakdown popup; clicking anywhere else on the row still opens Level 1 (`onOpen`) as before.

**Read `frontend/src/components/feed-v2/FeedRowV2.tsx`'s current content in full before editing** — this plan shows the complete new file content below, but confirm it matches what Phase 4 actually shipped before replacing it.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/components/feed-v2/FeedRowV2.test.tsx` (append to the existing test file — do not remove any existing tests):

```tsx
describe('FeedRowV2 intensity breakdown', () => {
  it('opens the intensity breakdown popup when the intensity bar/score is clicked, without opening the row', () => {
    const onOpen = vi.fn();
    render(<FeedRowV2 alert={makeAlert()} onOpen={onOpen} />);

    fireEvent.click(screen.getByTestId('intensity-tap-target'));

    expect(onOpen).not.toHaveBeenCalled();
    expect(screen.getByText("Intensity measures how hard the news hit this stock — not whether it's a good investment.")).toBeInTheDocument();
  });

  it('closes the breakdown popup via its own close button without opening the row', () => {
    const onOpen = vi.fn();
    render(<FeedRowV2 alert={makeAlert()} onOpen={onOpen} />);

    fireEvent.click(screen.getByTestId('intensity-tap-target'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Close'));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(onOpen).not.toHaveBeenCalled();
  });
});
```

(This assumes the existing `makeAlert` factory and `vi`/`render`/`screen`/`fireEvent` imports already present at the top of `FeedRowV2.test.tsx` from Phase 4 — reuse them, don't redefine.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/feed-v2/FeedRowV2.test.tsx`
Expected: FAIL — `getByTestId('intensity-tap-target')` finds nothing (the click target doesn't exist yet), and the popup text is never rendered.

- [ ] **Step 3: Implement**

Replace `frontend/src/components/feed-v2/FeedRowV2.tsx`'s content with:

```tsx
import { useState } from 'react';
import { formatExcess, intensityBandColorClass, verdictLabel } from '../../lib/feedV2Format';
import type { FeedV2Alert } from '../../lib/feedV2Api';
import AlertDetail from '../AlertDetail';
import IntensityBreakdownPopup from './IntensityBreakdownPopup';

interface FeedRowV2Props {
  alert: FeedV2Alert;
  onOpen: () => void;
}

export default function FeedRowV2({ alert, onOpen }: FeedRowV2Props) {
  const { text: excessText } = formatExcess(alert.excess_move_pct);
  const isMuted = alert.verdict === 'SECTOR_WIDE';
  const [breakdownOpen, setBreakdownOpen] = useState(false);

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        onClick={onOpen}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') onOpen();
        }}
        className="cursor-pointer border-b border-hairline py-[14px] last:border-b-0"
      >
        <div className="flex items-center gap-3">
          <span
            className={`min-w-[74px] shrink-0 font-data text-[19px] font-medium ${
              alert.direction === 'bullish' ? 'text-bullish' : 'text-bearish'
            }`}
          >
            {excessText}
          </span>
          <span className={`flex-1 truncate font-sans text-sm ${isMuted ? 'text-muted' : 'text-ink'}`}>
            {alert.summary_short}
          </span>
          {alert.in_my_holdings && (
            <span data-testid="owned-dot" className="h-[7px] w-[7px] shrink-0 rounded-full bg-accent" />
          )}
        </div>
        <div className="ml-[84px] flex items-center gap-2">
          <span className="rounded-full bg-elevated px-2 py-0.5 text-[11px] uppercase tracking-widest text-muted">
            {verdictLabel(alert.verdict)}
          </span>
          <span className="font-data text-[11px] text-muted">{alert.peak_ticker}</span>
          <button
            type="button"
            data-testid="intensity-tap-target"
            onClick={(e) => {
              e.stopPropagation();
              setBreakdownOpen(true);
            }}
            className="flex items-center gap-2"
            aria-label="View intensity breakdown"
          >
            <span className="h-1 w-full max-w-[130px] rounded-sm bg-elevated">
              <span
                className={`block h-full rounded-sm ${intensityBandColorClass(alert.intensity.band)}`}
                style={{ width: `${alert.intensity.score}%` }}
              />
            </span>
            <span className="font-data text-[11px] text-muted">{alert.intensity.score}</span>
          </button>
        </div>
      </div>
      <AlertDetail open={breakdownOpen} onClose={() => setBreakdownOpen(false)}>
        <IntensityBreakdownPopup intensity={alert.intensity} />
      </AlertDetail>
    </>
  );
}
```

Note the change from a single top-level `<div>` to a `<>...</>` Fragment wrapping the row `<div>` and `<AlertDetail>` as SIBLINGS — this is deliberate (see Global Constraints): `AlertDetail` is not portaled, so nesting it inside the row's `onClick` wrapper would let any click inside the open popup bubble up and re-trigger `onOpen`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/feed-v2/FeedRowV2.test.tsx`
Expected: all PASS (Phase 4's original 4 tests plus the 2 new ones).

- [ ] **Step 5: Run the full frontend suite to confirm no regressions**

Run: `cd frontend && npm test`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/feed-v2/FeedRowV2.tsx frontend/src/components/feed-v2/FeedRowV2.test.tsx
git commit -m "feat: wire IntensityBreakdownPopup into FeedRowV2's intensity bar/score"
```

---

## Task 3: Playwright screenshot verification (HARD RULE, extending Phase 4's spec)

**Files:**
- Modify: `frontend/e2e/feed-v2-screenshots.spec.ts`

**Context:** Playwright is already installed and configured (Phase 4). This task adds 4 new screenshots (popup open, dark/light × mobile/desktop) to the existing spec file and performs the same actually-look-at-them verification loop the task brief's HARD RULE requires — this phase has a new UI surface (the popup), so it needs its own visual check, not just a re-run of Phase 4's existing screenshots.

- [ ] **Step 1: Add the new screenshot cases**

Add to `frontend/e2e/feed-v2-screenshots.spec.ts`, inside the existing `for (const theme of THEMES)` loop, alongside the existing `Level 0`/`Level 1` test cases:

```ts
  test(`feed-v2 intensity breakdown (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const intensityTarget = page.getByTestId('intensity-tap-target').first();
    await intensityTarget.waitFor({ timeout: 10_000 });
    await intensityTarget.click();
    await page.waitForTimeout(300);
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-intensity-breakdown-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });
```

- [ ] **Step 2: Seed data and start both servers**

Run (mirroring Phase 4 Task 9's exact process):
```bash
cd backend && python seed_feed_v2_demo.py
cd backend && uvicorn app.main:app --port 8000 &
cd frontend && npm run dev &
```
Check port 8000/5173 aren't already occupied by another parallel session first (Phase 4's Task 9 hit this — use alternate ports and temporarily repoint `vite.config.ts`'s proxy / `playwright.config.ts`'s `baseURL` if needed, but **revert both to their committed values before committing anything** — do not let a workaround port leak into the commit).

- [ ] **Step 3: Run the screenshot spec**

Run: `cd frontend && npx playwright test`
Expected: 12 screenshots total now exist in `frontend/.superpowers-screenshots/` (Phase 4's original 8 plus these 4 new ones).

- [ ] **Step 4: Look at the 4 new screenshots — THE ACTUAL VERIFICATION STEP**

Open each of the 4 new PNGs (via the Read tool) and check against the spec:
- Large score number and band label clearly visible and legible in both themes.
- Each component row shows `label — raw ×weight` text and a mini bar; the three components (excess/volume/breadth) are all present and distinguishable from each other.
- The mini bars' fill color is the SAME band color as Phase 4's feed-row intensity bar (visual consistency — this is the same score, shown two ways).
- The disclaimer line is present, legible, and reads exactly *"Intensity measures how hard the news hit this stock — not whether it's a good investment."* in both themes.
- The popup itself doesn't look like it accidentally also triggered the Level 1 summary underneath (i.e., you see the breakdown popup content, not the raw-vs-sector reveal) — confirms the stopPropagation/sibling-rendering design actually works, not just in unit tests.

Write down every concrete discrepancy found. Fix it in `IntensityBreakdownPopup.tsx`/`FeedRowV2.tsx`/`index.css` as appropriate. Re-run Step 3 and re-check. Repeat until clean.

- [ ] **Step 5: Stop the background servers**

Kill the specific `uvicorn`/`npm run dev` PIDs started in Step 2 — never a broad process-kill.

- [ ] **Step 6: Run both full test suites one more time**

Run: `cd backend && python -m pytest -q` and `cd frontend && npm test` — confirm zero regressions from any fixes made in Step 4.

- [ ] **Step 7: Commit**

```bash
git add frontend/e2e/feed-v2-screenshots.spec.ts
git commit -m "feat: add Playwright screenshot verification for intensity breakdown popup"
```

If Step 4's review found and fixed anything, commit that separately, describing exactly what the screenshot review caught and corrected.

---

## Task 4: Full-suite regression check

- [ ] **Step 1: Run the entire backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS (this phase made zero backend changes).

- [ ] **Step 2: Run the entire frontend test suite**

Run: `cd frontend && npm test`
Expected: all tests PASS.

- [ ] **Step 3: Commit (only if Steps 1-2 required a fix)**

If clean, nothing to commit here.

---

## PHASE 5 STOP — required report

Report:
1. Full-suite pass/fail status, both backend and frontend.
2. All 4 new screenshots' final state — confirm each was actually opened and looked at, and list every concrete difference found during Task 3 Step 4's review and how it was fixed (or "clean on first pass" if nothing needed fixing).
3. Confirm the intensity tap target genuinely never triggers the row's `onOpen` (both by unit test and by visual screenshot check).
4. Confirm the disclaimer text is byte-for-byte identical to the spec's verbatim line.
5. Note again, for the record: the "fundamental note" section is deliberately absent (advisory tier, out of scope) — flag this so Phase 6/7 (which will reuse this popup for deep-dive/peer-row surfaces) and any future advisory-tier phase know where to extend it.

This plan ends here. Phase 6 (Level 2 ripple + Level 3 timeline) is a separate plan, written after this one ships and the report above is reviewed.
