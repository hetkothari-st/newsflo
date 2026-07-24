# Alert Charts Carousel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Present one alert chart at a time in a swipeable, tap-navigable mobile carousel and provide an explicit route back to Affected Companies.

**Architecture:** `AlertChartsPage` owns a numeric active-chart index and one ordered registry of render callbacks for the existing ten chart components. The existing `useHorizontalSwipe` hook advances or reverses that index, while accessible tap controls call the same bounded navigation functions. The page mounts only the active chart, preserving that chart's internal vertical layout while removing the page-long chart list.

**Tech Stack:** React 18, TypeScript, React Router 6, Tailwind CSS, Vitest, React Testing Library.

## Global Constraints

- Keep the existing ten chart components and their data/calculation logic unchanged.
- Add no dependencies; reuse `frontend/src/lib/useHorizontalSwipe.ts`.
- Preserve the existing Normal / Drilldown selector and loading/error states.
- The header action must route directly to `/alerts/:id`, never call `navigate(-1)`.
- Controls must have descriptive accessible names and native disabled states at carousel boundaries.
- The test must fail before production code is added or changed.

---

### Task 1: Cover carousel navigation at the page boundary

**Files:**
- Modify: `frontend/src/pages/AlertChartsPage.test.tsx`
- Modify: `frontend/src/pages/AlertChartsPage.tsx`

**Interfaces:**
- Consumes: `AlertChartsPage` at `/alerts/:id/charts`, mocked `getAlert`, and its existing ten chart headings.
- Produces: tests that assert one active chart, tap/swipe navigation, boundary disabling, and direct navigation to `/alerts/:id`.

- [ ] **Step 1: Write the failing tests**

  In `frontend/src/pages/AlertChartsPage.test.tsx`, add `fireEvent` to the testing-library import and render a second route that exposes the destination:

  ```tsx
  import { fireEvent, render, screen, waitFor } from '@testing-library/react';

  // Inside renderPage's <Routes>, after the charts route:
  <Route path="/alerts/:id" element={<p>Affected companies destination</p>} />
  ```

  Add these tests inside `describe('AlertChartsPage', ...)`:

  ```tsx
  it('shows one chart at a time and advances with the next control', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');

    expect(await screen.findByText('Multi-Level Impact Tree')).toBeInTheDocument();
    expect(screen.queryByText('Ripple Effect Graph')).not.toBeInTheDocument();
    expect(screen.getByText('Chart 1 of 10')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Next chart' }));

    expect(screen.getByText('Ripple Effect Graph')).toBeInTheDocument();
    expect(screen.queryByText('Multi-Level Impact Tree')).not.toBeInTheDocument();
    expect(screen.getByText('Chart 2 of 10')).toBeInTheDocument();
  });

  it('moves between charts with horizontal swipe gestures and stops at the boundaries', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');

    const carousel = await screen.findByTestId('chart-carousel');
    expect(screen.getByRole('button', { name: 'Previous chart' })).toBeDisabled();

    fireEvent.touchStart(carousel, { touches: [{ clientX: 240, clientY: 100 }] });
    fireEvent.touchMove(carousel, { touches: [{ clientX: 120, clientY: 105 }] });
    fireEvent.touchEnd(carousel, { changedTouches: [{ clientX: 120, clientY: 105 }] });

    expect(screen.getByText('Chart 2 of 10')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Previous chart' }));
    expect(screen.getByText('Chart 1 of 10')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous chart' })).toBeDisabled();
  });

  it('takes the user directly back to affected companies', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');

    fireEvent.click(await screen.findByRole('button', { name: 'Affected companies' }));

    expect(screen.getByText('Affected companies destination')).toBeInTheDocument();
  });
  ```

- [ ] **Step 2: Run the focused test file to verify it fails**

  Run: `npm test -- --run src/pages/AlertChartsPage.test.tsx`

  Expected: FAIL because `chart-carousel`, `Chart 1 of 10`, and the labelled controls do not exist; the direct destination test also fails because the header currently uses history back.

- [ ] **Step 3: Implement the carousel in `AlertChartsPage.tsx`**

  Add the hook import after the existing library imports:

  ```tsx
  import { useHorizontalSwipe } from '../lib/useHorizontalSwipe';
  ```

  Add active-card state and bounded functions immediately after the existing `breadth` state:

  ```tsx
  const [activeChartIndex, setActiveChartIndex] = useState(0);
  ```

  After `const graph = buildGraph(alert);`, define the ordered registry and navigation callbacks. Each callback must render the corresponding existing component with the exact props currently passed from the vertical list:

  ```tsx
  const charts = [
    { key: 'impact-tree', render: () => <ImpactTree companies={alert.companies} graph={graph} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'ripple-graph', render: () => <RippleGraph graph={graph} companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'supply-chain', render: () => <SupplyChainGraph graph={graph} companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'level-tree', render: () => <LevelTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'confidence-tree', render: () => <ConfidenceTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'split-tree', render: () => <SplitTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'timeline-tree', render: () => <TimelineTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'sector-tree', render: () => <SectorTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'economic-chain', render: () => <EconomicChain graph={graph} companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} /> },
    { key: 'knowledge-graph', render: () => <KnowledgeGraph graph={graph} companies={alert.companies} eventType={alert.event_type} /> },
  ];
  const goToPreviousChart = () => setActiveChartIndex((index) => Math.max(0, index - 1));
  const goToNextChart = () => setActiveChartIndex((index) => Math.min(charts.length - 1, index + 1));
  const swipeHandlers = useHorizontalSwipe({ onSwipeLeft: goToNextChart, onSwipeRight: goToPreviousChart });
  const activeChart = charts[activeChartIndex];
  ```

  Replace the header back button with this explicit route action:

  ```tsx
  <button type="button" onClick={() => navigate(`/alerts/${id}`)} aria-label="Affected companies" className="text-muted hover:text-ink">
    ←
  </button>
  ```

  Replace the current inner vertical-list `<div className="mx-auto ...">...</div>` with the active-card region:

  ```tsx
  <div className="mx-auto flex h-full w-full max-w-6xl flex-col px-4 py-4">
    <div
      data-testid="chart-carousel"
      className="flex min-h-0 flex-1 flex-col touch-pan-y"
      {...swipeHandlers}
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={goToPreviousChart}
          disabled={activeChartIndex === 0}
          aria-label="Previous chart"
          className="rounded-lg border border-hairline px-3 py-2 text-xs text-ink disabled:cursor-not-allowed disabled:opacity-40"
        >
          Previous
        </button>
        <p className="text-xs font-medium uppercase tracking-widest text-muted">Chart {activeChartIndex + 1} of {charts.length}</p>
        <button
          type="button"
          onClick={goToNextChart}
          disabled={activeChartIndex === charts.length - 1}
          aria-label="Next chart"
          className="rounded-lg border border-hairline px-3 py-2 text-xs text-ink disabled:cursor-not-allowed disabled:opacity-40"
        >
          Next
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pr-0.5" key={activeChart.key}>
        {activeChart.render()}
      </div>
    </div>
  </div>
  ```

- [ ] **Step 4: Run the focused test file to verify it passes**

  Run: `npm test -- --run src/pages/AlertChartsPage.test.tsx`

  Expected: PASS with all AlertChartsPage tests green.

- [ ] **Step 5: Commit the implemented carousel**

  ```bash
  git add frontend/src/pages/AlertChartsPage.tsx frontend/src/pages/AlertChartsPage.test.tsx
  git commit -m "feat: add swipeable alert charts"
  ```

### Task 2: Verify complete frontend compatibility

**Files:**
- Verify: `frontend/src/pages/AlertChartsPage.tsx`
- Verify: `frontend/src/pages/AlertChartsPage.test.tsx`

**Interfaces:**
- Consumes: the carousel implementation from Task 1.
- Produces: fresh repository-wide frontend test and build evidence.

- [ ] **Step 1: Run the complete frontend test suite**

  Run: `npm test`

  Expected: PASS with zero failing tests.

- [ ] **Step 2: Run the production typecheck and build**

  Run: `npm run build`

  Expected: exit code 0; TypeScript reports no errors and Vite emits the production bundle.

- [ ] **Step 3: Inspect the final change set**

  Run: `git diff HEAD~1 --check && git status --short`

  Expected: no whitespace errors; no unintended untracked or modified files.
