# Feed-v2 Photo Cards + Tabbed-Accordion Detail Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Revert feed-v2's alert detail from three separate routed pages back into a single popup with a tabbed-accordion (Affected · Ripple · Timeline, one section expanded at a time), and restyle feed-v2's feed rows from bare text into photo cards (article image + headline), matching the legacy feed's visual language without its swipeable-carousel interaction.

**Architecture:** Backend gains one new field (`image_url`) on an existing endpoint. Frontend deletes three routed pages and their routes, adds one new plain component (`AlertDetailPanel`, rendered inside the existing `AlertDetail` popup shell — not itself routed), rebuilds `FeedRowV2` as a photo card reusing `AlertCover`/`CategorySwatch` from the legacy feed, and reverts `FeedV2.tsx` to the fetch-and-open-a-popup pattern it used before the routed-pages design.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + react-router-dom + Tailwind (frontend), pytest (backend tests), Vitest + Testing Library (frontend tests), Playwright (screenshots).

## Global Constraints

- Spec source of truth for this revert: `docs/superpowers/specs/2026-07-27-feed-v2-photo-cards-and-detail-panel-design.md` — read before starting.
- Zero changes to the legacy `/` feed route (`FeedPage.tsx` and everything it renders).
- Zero changes to Level 4 (`StockDeepDivePage.tsx`, `/feed-v2/stock/:ticker`) or to `RippleSection.tsx`/`TimelineSection.tsx`'s own internals — only their container changes.
- Never fabricate: `why` renders as nothing (no placeholder) when null — unchanged from the prior design.
- HARD RULE for any UI-facing task: run the dev server and Playwright-screenshot every new/changed screen at 390px and 1920px, both dark and light mode, and actually look at the screenshots (via the Read tool) before calling the task done.
- Full backend and frontend test suites must both pass with zero regressions before this plan is considered done.

---

## File Map

```
backend/app/routers/feed_v2.py             MODIFY — _serialize gains article.image_url
backend/tests/test_feed_v2_router.py       MODIFY — tests for image_url on list + detail

frontend/src/lib/feedV2Api.ts              MODIFY — FeedV2Article gains image_url
frontend/src/components/feed-v2/AlertDetailPanel.tsx      CREATE — replaces the 3 routed pages
frontend/src/components/feed-v2/AlertDetailPanel.test.tsx CREATE
frontend/src/components/feed-v2/FeedRowV2.tsx              MODIFY — rebuilt as a photo card
frontend/src/components/feed-v2/FeedRowV2.test.tsx         MODIFY
frontend/src/components/feed-v2/FeedV2.tsx                 MODIFY — reverted to popup pattern
frontend/src/components/feed-v2/FeedV2.test.tsx            MODIFY
frontend/src/App.tsx                       MODIFY — remove 3 routes + imports
frontend/src/pages/AlertLevel1Page.tsx     DELETE
frontend/src/pages/AlertLevel1Page.test.tsx DELETE
frontend/src/pages/AlertRipplePage.tsx     DELETE
frontend/src/pages/AlertRipplePage.test.tsx DELETE
frontend/src/pages/AlertTimelinePage.tsx   DELETE
frontend/src/pages/AlertTimelinePage.test.tsx DELETE
frontend/e2e/feed-v2-screenshots.spec.ts   MODIFY — replace Level1/2/3 cases with feed-list + panel-tab cases
```

---

## Task 1: `article.image_url` on feed-v2 endpoints

**Files:**
- Modify: `backend/app/routers/feed_v2.py`
- Test: `backend/tests/test_feed_v2_router.py`

**Interfaces:**
- Produces: `article.image_url: string | null` in every `_serialize`d response — both `GET /api/feed-v2` (list) and `GET /api/feed-v2/{alert_id}` (detail), since both call `_serialize`. Consumed by Task 3 (`FeedRowV2`'s photo banner).

**Context:** `Article.image_url` already exists (`backend/app/models.py:75`, populated by `fetch_og_image`, already used by the legacy feed's `AlertCoverCard`) but `_serialize` in `app/routers/feed_v2.py` never includes it.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_feed_v2_router.py`, after `test_list_feed_v2_does_not_include_impact_companies`:

```python
def test_get_feed_v2_alert_includes_article_image_url(db_session):
    _override_db(db_session)
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()
    article = Article(
        source="test", url="https://example.com/img", title="Oil surges", content="c",
        image_url="https://example.com/photo.jpg",
    )
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=-4.2, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()
    client = TestClient(app)

    response = client.get(f"/api/feed-v2/{alert.id}")

    assert response.status_code == 200
    assert response.json()["article"]["image_url"] == "https://example.com/photo.jpg"
    app.dependency_overrides.clear()


def test_list_feed_v2_includes_article_image_url_null_when_absent(db_session):
    _override_db(db_session)
    _measured_alert(db_session)  # no image_url set -- Article defaults to None
    client = TestClient(app)

    response = client.get("/api/feed-v2")

    assert response.status_code == 200
    assert response.json()[0]["article"]["image_url"] is None
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_feed_v2_router.py -k image_url -v`
Expected: FAIL — `KeyError: 'image_url'`.

- [ ] **Step 3: Add the field**

In `backend/app/routers/feed_v2.py`, in `_serialize`'s `article` dict, add `image_url` after `"id"`:

```python
        "article": {
            "id": alert.article.id,
            "image_url": alert.article.image_url,
            "title": alert.article.title,
            "url": alert.article.url,
            "source": alert.article.source,
            "published_at": alert.article.published_at.isoformat() if alert.article.published_at else None,
        },
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_feed_v2_router.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/feed_v2.py backend/tests/test_feed_v2_router.py
git commit -m "feat: expose article.image_url on feed-v2 endpoints"
```

---

## Task 2: `AlertDetailPanel` — the tabbed-accordion detail content

**Files:**
- Modify: `frontend/src/lib/feedV2Api.ts`
- Create: `frontend/src/components/feed-v2/AlertDetailPanel.tsx`
- Test: `frontend/src/components/feed-v2/AlertDetailPanel.test.tsx`

**Interfaces:**
- Consumes: `RippleSection` (existing, unchanged, props `{companies: RippleCompany[], alertId: number}`); `TimelineSection` (existing, unchanged, props `{entries: TimelineEntry[]}`); `formatExcess`/`verdictLabel` (existing, `frontend/src/lib/feedV2Format.ts`); `FeedV2Alert` type (existing, gains `image_url` on its nested article in this task).
- Produces: default-exported `AlertDetailPanel` component, props `{alert: FeedV2Alert}`. Consumed by Task 4 (rendered inside `FeedV2.tsx`'s `AlertDetail` popup, replacing the deleted routed pages).

**Context:** This component's summary block and "Affected" tab body are the same markup that lived in `AlertLevel1Page.tsx` (being deleted in Task 4) — moved here verbatim, just re-composed as one of three collapsible tab bodies instead of a standalone page. `RippleSection`/`TimelineSection` already render their own `rounded-lg bg-surface p-5` wrapper internally — do NOT add a second surface/padding wrapper around them here (only the "Affected" tab body and the empty-state lines need their own `p-5`, since impact-core rows have no self-contained wrapper).

- [ ] **Step 1: Add `image_url` to `FeedV2Article`**

In `frontend/src/lib/feedV2Api.ts`, add to the `FeedV2Article` interface:

```ts
export interface FeedV2Article {
  id: number;
  image_url: string | null;
  title: string;
  url: string;
  source: string;
  published_at: string | null;
}
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/components/feed-v2/AlertDetailPanel.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AlertDetailPanel from './AlertDetailPanel';
import type { FeedV2Alert } from '../../lib/feedV2Api';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

function makeAlert(overrides: Partial<FeedV2Alert> = {}): FeedV2Alert {
  return {
    id: 1,
    category: 'oil_gas',
    created_at: '2026-07-22T10:00:00Z',
    summary_short: 'Oil supply shock lifts refiners',
    summary_long: 'Crude prices jumped on a supply disruption. Refiners face wider margin pressure.',
    article: {
      id: 1, image_url: null, title: 'Oil surges', url: 'https://example.com/a',
      source: 'Economic Times', published_at: null,
    },
    excess_move_pct: -4.2,
    direction: 'bearish',
    raw_move_pct: -4.8,
    sector_move_pct: -0.6,
    volume_multiple: 3.1,
    benchmark_ticker: '^CNXENERGY',
    is_fallback_benchmark: false,
    peak_ticker: 'RELIANCE.NS',
    peak_company_name: 'Reliance Industries',
    verdict: 'COMPANY_SPECIFIC',
    intensity: { score: 82, band: 'High', components: [] },
    breadth_score: 40,
    in_my_holdings: false,
    impact_companies: [
      {
        ticker: 'RELIANCE.NS', name: 'Reliance Industries', direction: 'bearish',
        excess_move_pct: -4.2, why: 'Refining margins compress as crude input costs rise.',
      },
    ],
    ripple: [
      {
        ticker: 'BPCL.NS', name: 'Bharat Petroleum', sector: 'oil_gas', cap_tier: 'LARGE',
        business_desc: 'Refines petroleum.', relationship: 'BENEFICIARY', direction: 'bullish',
        excess_move_pct: 3.0, intensity: { score: 70, band: 'Moderate', components: [] },
        is_exposure_only: false, in_my_holdings: false,
      },
    ],
    timeline: [{ horizon: 'TODAY', description: 'Markets react immediately.' }],
    ...overrides,
  };
}

function renderPanel(alert = makeAlert()) {
  return render(
    <MemoryRouter>
      <AlertDetailPanel alert={alert} />
    </MemoryRouter>,
  );
}

describe('AlertDetailPanel', () => {
  it('renders the summary always, with no tab expanded initially', () => {
    renderPanel();
    expect(screen.getByText(/Crude prices jumped/)).toBeInTheDocument();
    expect(screen.queryByText('RELIANCE.NS')).not.toBeInTheDocument();
    expect(screen.queryByText('BPCL.NS')).not.toBeInTheDocument();
  });

  it('renders tab labels with counts', () => {
    renderPanel();
    expect(screen.getByRole('button', { name: 'Affected (1)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ripple (1)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Timeline (1)' })).toBeInTheDocument();
  });

  it('expands the Affected tab on click, showing why text', () => {
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Affected (1)' }));
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
    expect(screen.getByText('Refining margins compress as crude input costs rise.')).toBeInTheDocument();
  });

  it('collapses the Affected tab when clicked again', () => {
    renderPanel();
    const affectedTab = screen.getByRole('button', { name: 'Affected (1)' });
    fireEvent.click(affectedTab);
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
    fireEvent.click(affectedTab);
    expect(screen.queryByText('RELIANCE.NS')).not.toBeInTheDocument();
  });

  it('switches from Affected to Ripple, collapsing Affected', () => {
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Affected (1)' }));
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Ripple (1)' }));
    expect(screen.queryByText('RELIANCE.NS')).not.toBeInTheDocument();
    expect(screen.getByText('BPCL.NS')).toBeInTheDocument();
  });

  it('expands the Timeline tab and shows entries', () => {
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Timeline (1)' }));
    expect(screen.getByText('Markets react immediately.')).toBeInTheDocument();
  });

  it('shows a quiet fallback line for an empty tab instead of hiding it', () => {
    renderPanel(makeAlert({ impact_companies: [] }));
    expect(screen.getByRole('button', { name: 'Affected (0)' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Affected (0)' }));
    expect(screen.getByText('No affected companies found.')).toBeInTheDocument();
  });

  it('navigates to the stock deep-dive when an affected row is clicked', () => {
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Affected (1)' }));
    fireEvent.click(screen.getByRole('button', { name: /RELIANCE\.NS/ }));
    expect(mockNavigate).toHaveBeenCalledWith('/feed-v2/stock/RELIANCE.NS?alertId=1');
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npm test -- --run AlertDetailPanel`
Expected: FAIL — `Failed to resolve import "./AlertDetailPanel"`.

- [ ] **Step 4: Implement `AlertDetailPanel`**

Create `frontend/src/components/feed-v2/AlertDetailPanel.tsx`:

```tsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatExcess, verdictLabel } from '../../lib/feedV2Format';
import type { FeedV2Alert } from '../../lib/feedV2Api';
import RippleSection from './RippleSection';
import TimelineSection from './TimelineSection';

type TabKey = 'affected' | 'ripple' | 'timeline';

function signedPct(value: number): string {
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}%`;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

interface AlertDetailPanelProps {
  alert: FeedV2Alert;
}

export default function AlertDetailPanel({ alert }: AlertDetailPanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey | null>(null);
  const navigate = useNavigate();

  const impactCompanies = alert.impact_companies ?? [];
  const ripple = alert.ripple ?? [];
  const timeline = alert.timeline ?? [];

  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: 'affected', label: 'Affected', count: impactCompanies.length },
    { key: 'ripple', label: 'Ripple', count: ripple.length },
    { key: 'timeline', label: 'Timeline', count: timeline.length },
  ];

  function toggleTab(key: TabKey) {
    setActiveTab((current) => (current === key ? null : key));
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg bg-surface p-5">
        <span className="rounded-full bg-elevated px-2 py-0.5 text-[11px] uppercase tracking-widest text-muted">
          {verdictLabel(alert.verdict)}
        </span>
        {alert.summary_long && (
          <p className="mt-3 font-sans text-sm text-ink">{alert.summary_long}</p>
        )}
      </div>

      <div className="rounded-lg bg-surface p-5">
        <div className="flex gap-6">
          <div>
            <div className="font-sans text-xs text-muted">Raw move</div>
            <div
              className={`font-data text-lg font-medium ${
                alert.raw_move_pct >= 0 ? 'text-bullish' : 'text-bearish'
              }`}
            >
              {signedPct(alert.raw_move_pct)}
            </div>
          </div>
          <div>
            <div className="font-sans text-xs text-muted">Sector move</div>
            <div className="font-data text-lg font-medium text-muted">{signedPct(alert.sector_move_pct)}</div>
          </div>
        </div>
        {alert.volume_multiple !== null && (
          <div className="mt-3 font-data text-sm text-ink">
            {alert.volume_multiple.toFixed(1)}× average volume
          </div>
        )}
      </div>

      <div className="rounded-lg bg-surface p-5">
        <div className="font-sans text-xs text-muted">
          {alert.article.source} &middot; {alert.is_fallback_benchmark ? 'vs Nifty 50' : 'vs sector index'}
        </div>
        <time className="mt-1 block font-sans text-xs text-muted" dateTime={alert.created_at}>
          {formatTime(alert.created_at)}
        </time>
      </div>

      <div className="rounded-lg bg-surface">
        <div className="flex border-b border-hairline">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => toggleTab(tab.key)}
              className={`flex-1 border-b-2 px-3 py-3 font-sans text-xs uppercase tracking-widest ${
                activeTab === tab.key ? 'border-accent text-ink' : 'border-transparent text-muted'
              }`}
            >
              {tab.label} ({tab.count})
            </button>
          ))}
        </div>

        {activeTab === 'affected' && (
          <div className="p-5">
            {impactCompanies.length === 0 ? (
              <p className="font-sans text-sm text-muted">No affected companies found.</p>
            ) : (
              <div className="flex flex-col gap-4">
                {impactCompanies.map((company) => (
                  <div
                    key={company.ticker}
                    role="button"
                    tabIndex={0}
                    aria-label={company.ticker}
                    onClick={() => navigate(`/feed-v2/stock/${company.ticker}?alertId=${alert.id}`)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        navigate(`/feed-v2/stock/${company.ticker}?alertId=${alert.id}`);
                      }
                    }}
                    className="cursor-pointer"
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-data text-[11px] text-muted">{company.ticker}</span>
                      <span
                        className={`font-data text-xs ${
                          company.direction === 'bullish' ? 'text-bullish' : 'text-bearish'
                        }`}
                      >
                        {formatExcess(company.excess_move_pct).text}
                      </span>
                    </div>
                    {company.why && <p className="mt-1 font-sans text-[13px] text-ink">{company.why}</p>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'ripple' &&
          (ripple.length === 0 ? (
            <p className="p-5 font-sans text-sm text-muted">No ripple detected.</p>
          ) : (
            <RippleSection companies={ripple} alertId={alert.id} />
          ))}

        {activeTab === 'timeline' &&
          (timeline.length === 0 ? (
            <p className="p-5 font-sans text-sm text-muted">No timeline available.</p>
          ) : (
            <TimelineSection entries={timeline} />
          ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npm test -- --run AlertDetailPanel`
Expected: all 8 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/feedV2Api.ts frontend/src/components/feed-v2/AlertDetailPanel.tsx frontend/src/components/feed-v2/AlertDetailPanel.test.tsx
git commit -m "feat: AlertDetailPanel -- tabbed-accordion detail content, one section expanded at a time"
```

---

## Task 3: `FeedRowV2` rebuilt as a photo card

**Files:**
- Modify: `frontend/src/components/feed-v2/FeedRowV2.tsx`
- Modify: `frontend/src/components/feed-v2/FeedRowV2.test.tsx`

**Interfaces:**
- Consumes: `AlertCover` (existing, unchanged, `frontend/src/components/AlertCover.tsx`, props `{imageUrl: string | null, category: string}`); `CategorySwatch` (existing, unchanged, `frontend/src/components/CategorySwatch.tsx`, props `{category: string, active?: boolean, label?: string}`); `FeedV2Article.image_url` (Task 2).
- Produces: `FeedRowV2` keeps its existing public interface (`{alert: FeedV2Alert, onOpen: () => void}`) unchanged — only its internal markup changes. Consumed unchanged by Task 4's `FeedV2.tsx`.

**Context:** `alert.category` is already a plain string on `FeedV2Alert` (used today only for the intensity band, not yet for any visual swatch) — `AlertCover`/`CategorySwatch` both key off exactly this taxonomy (`backend/app/analysis/schemas.py` `CATEGORIES`), same one this codebase already uses everywhere else. See `frontend/src/components/AlertCoverCard.tsx`'s carousel-card usage of both components for the reference visual pattern this task mirrors (small pill chips over the image, not the full-width gradient wash the grid variant uses).

- [ ] **Step 1: Write the failing tests**

In `frontend/src/components/feed-v2/FeedRowV2.test.tsx`, first add `image_url: null` to the existing `makeAlert()` fixture's `article` object:

```tsx
    article: { id: 1, image_url: null, title: 'Oil surges', url: 'https://example.com/a', source: 'test', published_at: null },
```

Then add these two tests inside the existing `describe('FeedRowV2', ...)` block:

```tsx
  it('renders the article headline and category', () => {
    render(<FeedRowV2 alert={makeAlert()} onOpen={() => {}} />);
    expect(screen.getByText('Oil surges')).toBeInTheDocument();
    expect(screen.getByText('Oil & Gas')).toBeInTheDocument();
  });

  it('renders the article photo when image_url is present', () => {
    const { container } = render(
      <FeedRowV2
        alert={makeAlert({
          article: {
            id: 1, image_url: 'https://example.com/photo.jpg', title: 'Oil surges',
            url: 'https://example.com/a', source: 'test', published_at: null,
          },
        })}
        onOpen={() => {}}
      />,
    );
    expect(container.querySelector('img[src="https://example.com/photo.jpg"]')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npm test -- --run FeedRowV2`
Expected: FAIL — TypeScript error (missing `image_url` on the fixture before Step 1's fixture edit is applied) or, once the fixture is fixed, the two new assertions fail (no headline/category/photo markup exists yet).

- [ ] **Step 3: Rebuild `FeedRowV2`**

Replace the full contents of `frontend/src/components/feed-v2/FeedRowV2.tsx`:

```tsx
import { useState } from 'react';
import { formatExcess, intensityBandColorClass, verdictLabel } from '../../lib/feedV2Format';
import type { FeedV2Alert } from '../../lib/feedV2Api';
import AlertCover from '../AlertCover';
import AlertDetail from '../AlertDetail';
import CategorySwatch from '../CategorySwatch';
import IntensityBreakdownPopup from './IntensityBreakdownPopup';

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

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
        className="cursor-pointer overflow-hidden rounded-lg bg-surface p-3 theme-light:shadow-neu"
      >
        <div className="relative h-40 w-full overflow-hidden rounded-md">
          <AlertCover imageUrl={alert.article.image_url} category={alert.category} />
          <div className="absolute inset-x-0 top-0 flex items-center justify-between p-3">
            <span className="inline-flex items-center rounded-full bg-page/85 px-2.5 py-1 backdrop-blur-sm">
              <CategorySwatch category={alert.category} active />
            </span>
            <time className="rounded-full bg-page/85 px-2.5 py-1 text-xs uppercase tracking-widest text-ink backdrop-blur-sm">
              {formatTime(alert.created_at)}
            </time>
          </div>
        </div>

        <h2 className="mt-3 line-clamp-2 font-sans text-lg font-semibold leading-snug text-ink">
          {alert.article.title}
        </h2>

        <div className="mt-2 flex items-center gap-3">
          <span
            className={`shrink-0 font-data text-[17px] font-medium ${
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

        <div className="mt-2 flex items-center gap-2">
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
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') e.stopPropagation();
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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npm test -- --run FeedRowV2`
Expected: all tests PASS (6 pre-existing + 2 new). The pre-existing tests (excess/verdict/ticker/score, bearish/bullish arrow, owned-dot, onOpen click, and both intensity-breakdown tests) all still pass unchanged — this task only added markup around them, it didn't remove or rename anything they assert on.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/feed-v2/FeedRowV2.tsx frontend/src/components/feed-v2/FeedRowV2.test.tsx
git commit -m "feat: rebuild FeedRowV2 as a photo card (article image + headline)"
```

---

## Task 4: Revert `FeedV2` to the popup pattern, delete the 3 routed pages

**Files:**
- Modify: `frontend/src/components/feed-v2/FeedV2.tsx`
- Modify: `frontend/src/components/feed-v2/FeedV2.test.tsx`
- Modify: `frontend/src/App.tsx`
- Delete: `frontend/src/pages/AlertLevel1Page.tsx`, `AlertLevel1Page.test.tsx`
- Delete: `frontend/src/pages/AlertRipplePage.tsx`, `AlertRipplePage.test.tsx`
- Delete: `frontend/src/pages/AlertTimelinePage.tsx`, `AlertTimelinePage.test.tsx`

**Interfaces:**
- Consumes: `AlertDetailPanel` (Task 2); `FeedRowV2` (Task 3, unchanged public interface).
- Produces: `/feed-v2/alert/:id`, `/feed-v2/alert/:id/ripple`, `/feed-v2/alert/:id/timeline` routes no longer exist. Tapping a feed row opens `AlertDetailPanel` inside the existing `AlertDetail` popup shell — no navigation, no URL change.

- [ ] **Step 1: Replace `FeedV2.tsx`**

Replace the full contents of `frontend/src/components/feed-v2/FeedV2.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../lib/auth';
import { getFeedV2Alert, getFeedV2Alerts, type FeedV2Alert } from '../../lib/feedV2Api';
import AlertDetail from '../AlertDetail';
import AlertDetailPanel from './AlertDetailPanel';
import FeedRowV2 from './FeedRowV2';

export default function FeedV2() {
  const { token } = useAuth();
  const [alerts, setAlerts] = useState<FeedV2Alert[]>([]);
  const [openAlert, setOpenAlert] = useState<FeedV2Alert | null>(null);

  useEffect(() => {
    getFeedV2Alerts(token).then(setAlerts).catch(() => setAlerts([]));
  }, [token]);

  const handleOpen = (id: number) => {
    getFeedV2Alert(id, token)
      .then(setOpenAlert)
      .catch(() => setOpenAlert(null));
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-4">
      <div className="mb-2 flex justify-end">
        <Link to="/feed-v2/directory" className="font-sans text-xs text-muted underline">
          Browse all stocks
        </Link>
      </div>
      <div className="flex flex-col gap-4">
        {alerts.map((alert) => (
          <FeedRowV2 key={alert.id} alert={alert} onOpen={() => handleOpen(alert.id)} />
        ))}
      </div>
      <AlertDetail open={openAlert !== null} onClose={() => setOpenAlert(null)}>
        {openAlert && <AlertDetailPanel alert={openAlert} />}
      </AlertDetail>
    </div>
  );
}
```

- [ ] **Step 2: Replace `FeedV2.test.tsx`**

Replace the full contents of `frontend/src/components/feed-v2/FeedV2.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FeedV2 from './FeedV2';
import * as feedV2Api from '../../lib/feedV2Api';
import { AuthProvider } from '../../lib/auth';
import type { FeedV2Alert } from '../../lib/feedV2Api';

function makeAlert(overrides: Partial<FeedV2Alert> = {}): FeedV2Alert {
  return {
    id: 1,
    category: 'oil_gas',
    created_at: '2026-07-22T10:00:00Z',
    summary_short: 'Oil supply shock lifts refiners',
    summary_long: 'Crude prices jumped on a supply disruption. Refiners face wider margin pressure.',
    article: {
      id: 1, image_url: null, title: 'Oil surges', url: 'https://example.com/a',
      source: 'Economic Times', published_at: null,
    },
    excess_move_pct: -4.2,
    direction: 'bearish',
    raw_move_pct: -4.8,
    sector_move_pct: -0.6,
    volume_multiple: 3.1,
    benchmark_ticker: '^CNXENERGY',
    is_fallback_benchmark: false,
    peak_ticker: 'RELIANCE.NS',
    peak_company_name: 'Reliance Industries',
    verdict: 'COMPANY_SPECIFIC',
    intensity: { score: 82, band: 'High', components: [] },
    breadth_score: 40,
    in_my_holdings: false,
    ...overrides,
  };
}

function renderFeedV2() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <FeedV2 />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('FeedV2', () => {
  it('fetches and renders feed rows', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alerts').mockResolvedValue([makeAlert()]);
    renderFeedV2();
    await waitFor(() => expect(screen.getByText('Oil surges')).toBeInTheDocument());
  });

  it('opens the detail panel when a row is clicked', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alerts').mockResolvedValue([makeAlert()]);
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    const { user } = await import('@testing-library/user-event').then((m) => ({ user: m.default.setup() }));
    renderFeedV2();
    await waitFor(() => screen.getByText('Oil surges'));
    await user.click(screen.getByText('Oil surges'));
    await waitFor(() =>
      expect(screen.getByText(/Crude prices jumped on a supply disruption/)).toBeInTheDocument(),
    );
  });

  it('renders nothing extra when the feed is empty', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alerts').mockResolvedValue([]);
    renderFeedV2();
    await waitFor(() => expect(feedV2Api.getFeedV2Alerts).toHaveBeenCalled());
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders a link to the stock directory', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alerts').mockResolvedValue([]);
    renderFeedV2();
    await waitFor(() => expect(feedV2Api.getFeedV2Alerts).toHaveBeenCalled());
    expect(screen.getByRole('link', { name: 'Browse all stocks' })).toHaveAttribute(
      'href',
      '/feed-v2/directory',
    );
  });
});
```

- [ ] **Step 3: Remove the 3 routes from `App.tsx`**

In `frontend/src/App.tsx`, remove these three import lines:

```tsx
import AlertLevel1Page from './pages/AlertLevel1Page';
import AlertRipplePage from './pages/AlertRipplePage';
import AlertTimelinePage from './pages/AlertTimelinePage';
```

And remove these three route lines:

```tsx
        <Route path="/feed-v2/alert/:id" element={<AlertLevel1Page />} />
        <Route path="/feed-v2/alert/:id/ripple" element={<AlertRipplePage />} />
        <Route path="/feed-v2/alert/:id/timeline" element={<AlertTimelinePage />} />
```

`/feed-v2/stock/:ticker` (Level 4) and `/feed-v2/directory` stay exactly as they are.

- [ ] **Step 4: Delete the 3 routed pages**

```bash
git rm frontend/src/pages/AlertLevel1Page.tsx frontend/src/pages/AlertLevel1Page.test.tsx
git rm frontend/src/pages/AlertRipplePage.tsx frontend/src/pages/AlertRipplePage.test.tsx
git rm frontend/src/pages/AlertTimelinePage.tsx frontend/src/pages/AlertTimelinePage.test.tsx
```

- [ ] **Step 5: Run the affected tests**

Run: `cd frontend && npm test -- --run FeedV2`
Expected: all 4 tests PASS.

- [ ] **Step 6: Run the full frontend suite**

Run: `cd frontend && npm test -- --run`
Expected: all PASS, zero failures — confirms nothing else referenced the three deleted pages.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/feed-v2/FeedV2.tsx frontend/src/components/feed-v2/FeedV2.test.tsx
git add frontend/src/pages/AlertLevel1Page.tsx frontend/src/pages/AlertLevel1Page.test.tsx
git add frontend/src/pages/AlertRipplePage.tsx frontend/src/pages/AlertRipplePage.test.tsx
git add frontend/src/pages/AlertTimelinePage.tsx frontend/src/pages/AlertTimelinePage.test.tsx
git commit -m "feat: revert feed-v2 alert detail to a single popup (AlertDetailPanel), delete the 3 routed pages"
```

---

## Task 5: Playwright screenshot verification (HARD RULE)

**Files:**
- Modify: `frontend/e2e/feed-v2-screenshots.spec.ts`

**Context:** This replaces the prior plan's Level 1/2/3 routed-page screenshot cases (now obsolete — those pages are deleted) with a feed-list case (photo cards) and three detail-panel cases (one per tab, all reached via the same popup opened from the same row, verifying the tab-switch/collapse behavior visually). The intensity-breakdown, directory, and "stock deep-dive without alert context" cases are unchanged. "Stock deep-dive with alert context" changes its navigation chain: it now opens the popup, clicks the Ripple tab, then clicks a peer row (all within the popup, no page navigation until the final deep-dive tap).

- [ ] **Step 1: Replace the full contents of `frontend/e2e/feed-v2-screenshots.spec.ts`**

```ts
import { test } from '@playwright/test';

const THEMES = ['dark', 'light'] as const;

for (const theme of THEMES) {
  test(`feed-v2 list (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    await page.waitForSelector('text=/./', { timeout: 10_000 }).catch(() => {});
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-list-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 detail panel - affected tab (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    // The popup issues its own async fetch after opening -- wait for
    // content that only renders once that fetch resolves.
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    await page.getByRole('button', { name: /Affected/ }).click();
    await page.waitForTimeout(300);
    await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"]') as HTMLElement | null;
      const body = dialog?.querySelector('.overflow-y-auto') as HTMLElement | null;
      if (dialog) {
        dialog.style.overflow = 'visible';
        dialog.style.maxHeight = 'none';
      }
      if (body) {
        body.style.overflow = 'visible';
        body.style.maxHeight = 'none';
      }
    });
    await page.locator('[role="dialog"]').screenshot({
      path: `.superpowers-screenshots/feed-v2-panel-affected-${theme}-${test.info().project.name}.png`,
    });
  });

  test(`feed-v2 detail panel - ripple tab (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    await page.getByRole('button', { name: /Ripple/ }).click();
    await page.waitForTimeout(300);
    await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"]') as HTMLElement | null;
      const body = dialog?.querySelector('.overflow-y-auto') as HTMLElement | null;
      if (dialog) {
        dialog.style.overflow = 'visible';
        dialog.style.maxHeight = 'none';
      }
      if (body) {
        body.style.overflow = 'visible';
        body.style.maxHeight = 'none';
      }
    });
    await page.locator('[role="dialog"]').screenshot({
      path: `.superpowers-screenshots/feed-v2-panel-ripple-${theme}-${test.info().project.name}.png`,
    });
  });

  test(`feed-v2 detail panel - timeline tab (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    await page.getByRole('button', { name: /Timeline/ }).click();
    await page.waitForTimeout(300);
    await page.evaluate(() => {
      const dialog = document.querySelector('[role="dialog"]') as HTMLElement | null;
      const body = dialog?.querySelector('.overflow-y-auto') as HTMLElement | null;
      if (dialog) {
        dialog.style.overflow = 'visible';
        dialog.style.maxHeight = 'none';
      }
      if (body) {
        body.style.overflow = 'visible';
        body.style.maxHeight = 'none';
      }
    });
    await page.locator('[role="dialog"]').screenshot({
      path: `.superpowers-screenshots/feed-v2-panel-timeline-${theme}-${test.info().project.name}.png`,
    });
  });

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

  test(`feed-v2 stock deep-dive with alert context (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    await page.getByRole('button', { name: /Ripple/ }).click();
    const peerRow = page.locator('[role="dialog"] [role="button"][aria-label]').first();
    await peerRow.waitFor({ timeout: 10_000 });
    await peerRow.click();
    await page.waitForSelector('text=What they do', { timeout: 10_000 });
    await page.evaluate(() => {
      const bottomNav = document.querySelector('nav.fixed') as HTMLElement | null;
      if (bottomNav) bottomNav.style.display = 'none';
    });
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-stock-deep-dive-with-alert-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 directory (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2/directory');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    await page.waitForSelector('text=/./', { timeout: 10_000 }).catch(() => {});
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-directory-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 stock deep-dive without alert context (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2/directory');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstCompanyLink = page.locator('a[href^="/feed-v2/stock/"]').first();
    await firstCompanyLink.waitFor({ timeout: 10_000 });
    await firstCompanyLink.click();
    await page.waitForSelector('text=What they do', { timeout: 10_000 });
    await page.evaluate(() => {
      const bottomNav = document.querySelector('nav.fixed') as HTMLElement | null;
      if (bottomNav) bottomNav.style.display = 'none';
    });
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-stock-deep-dive-no-alert-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });
}
```

- [ ] **Step 2: Seed data and start both servers**

```bash
cd backend && python seed_feed_v2_demo.py
```

Start the backend and frontend dev servers as background processes. Check port availability first (see this project's own established convention — a prior session found `frontend/node_modules`'s `@playwright/test` was declared but never actually installed anywhere in this repo; if `npx playwright test` fails to find it, run `npm install` in this worktree's `frontend/` first — this replaces the NTFS junction to the shared `node_modules` with a real local install, which is expected and fine for this worktree).

- [ ] **Step 3: Run the screenshot spec**

Run: `cd frontend && npx playwright test feed-v2-screenshots`
Expected: all tests pass — 8 test names × 2 themes × 2 device projects (mobile/desktop) = 32 screenshots.

- [ ] **Step 4: Look at every new/changed screenshot — THE ACTUAL VERIFICATION STEP**

Open each of these with the Read tool (both themes, both mobile/desktop projects) and check against `docs/superpowers/specs/2026-07-27-feed-v2-photo-cards-and-detail-panel-design.md`:
- **`feed-v2-list-*`:** each row is a self-contained card — photo banner (or category-tinted placeholder if no image) with category badge + time overlaid, headline below the photo, then the excess/why/verdict/ticker/intensity skim row beneath the headline. Cards visually separated by gaps, not one shared bordered box. No clipped headline text (2-line clamp).
- **`feed-v2-panel-affected-*`:** summary block always visible above the tab strip; "Affected" tab active/underlined; impact-core rows visible (ticker + signed % + why where present); "Ripple"/"Timeline" tabs visible but NOT expanded (only one section body at a time).
- **`feed-v2-panel-ripple-*`:** same summary block; "Ripple" tab active; ripple content visible (grouped by relationship, matching its established appearance); "Affected" content NOT visible.
- **`feed-v2-panel-timeline-*`:** same summary block; "Timeline" tab active; timeline content visible; nothing else expanded.
- **`feed-v2-stock-deep-dive-with-alert-*`:** unchanged in appearance from prior phases — re-confirm nothing regressed now that it's reached via the popup's Ripple tab instead of a routed page.
- Every screenshot: both themes legible, no clipped/overlapping text, tab strip's active-tab underline visually distinct in both themes, mobile `BottomNav` correctly hidden where applicable (deep-dive screenshots only — the feed list and popup screenshots don't need it hidden, since neither is a `fullPage` capture of a page taller than one viewport in the same way the deep-dive page is).

Write down every concrete discrepancy found. Fix it in the relevant component. Re-run Step 3 and re-check. Repeat until clean.

- [ ] **Step 5: Stop the background servers**

Kill the specific PIDs — never a broad process-kill.

- [ ] **Step 6: Run both full test suites one more time**

Run: `cd backend && python -m pytest -q` and `cd frontend && npm test -- --run` — confirm zero regressions from any Step 4 fixes.

- [ ] **Step 7: Commit**

```bash
git add frontend/e2e/feed-v2-screenshots.spec.ts
git commit -m "test: rewrite feed-v2 screenshots for photo-card list + tabbed detail panel"
```

---

## Task 6: Full-suite regression check

- [ ] **Step 1: Run the entire backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS, zero failures.

- [ ] **Step 2: Run the entire frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: all tests PASS, zero failures.

- [ ] **Step 3: Confirm the legacy `/` feed is untouched**

Run: `git diff master --stat -- frontend/src/pages/FeedPage.tsx frontend/src/components/Feed.tsx`
Expected: no output.

- [ ] **Step 4: Confirm Level 4 is untouched**

Run: `git diff master --stat -- frontend/src/pages/StockDeepDivePage.tsx`
Expected: no output.

- [ ] **Step 5: Report**

Summarize: total commits, final test counts (backend/frontend), confirmation that all 32 screenshots were opened and reviewed (list any discrepancies found during Task 5 and how each was fixed, or "clean on first pass").
