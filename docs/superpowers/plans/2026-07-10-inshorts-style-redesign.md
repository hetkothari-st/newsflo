# Inshorts-Style Feed Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace NewsFlo's scrollable alert-card list with an Inshorts-inspired feed — full-screen swipe-through cards on mobile, a bold card grid on desktop — while keeping the existing dark CRED-style visual base.

**Architecture:** New presentational/container components (`AlertCoverCard`, `AlertCompanies`, `AlertDetail`, `MobileFeedCarousel`, `DesktopFeedGrid`, `BottomNav`, `CategoryTabs`) replace `AlertCard.tsx` and `FeedTabs.tsx`. `Feed.tsx` becomes the single owner of tab state, socket state, and which alert's detail is open; both layout containers render from the same fetched data and are toggled by CSS breakpoint (`md:`), not JS viewport detection.

**Tech Stack:** React 18 + TypeScript + Vite + Tailwind CSS 3.4 + Vitest + Testing Library. No new dependencies — swipe uses native CSS scroll-snap.

## Global Constraints

- Frontend only (`frontend/src/`) — no backend/API changes. Spec: `docs/superpowers/specs/2026-07-10-inshorts-style-redesign-design.md`.
- Keep the existing dark theme tokens (`page`/`surface`/`hairline`/`ink`/`muted`/`bullish`/`bearish`/`swatch-*` in `tailwind.config.ts`) — do not add new colors.
- Keep the Georgia serif display font for headlines — do not swap typefaces.
- No new npm dependencies (no gesture/animation libraries) — use native CSS scroll-snap and `motion-safe:`/`motion-reduce:` (already used throughout this codebase).
- Every new interactive element needs a keyboard path (Enter/Space to activate, Esc to close overlays) — matches this codebase's existing pattern (see current `AlertCard.tsx`'s `onKeyDown` handlers).
- Run `npx vitest run` and `npx tsc --noEmit` (from `frontend/`) after every task; both must be clean before moving on.

---

## File Structure

**New files:**
- `frontend/src/components/AlertCompanies.tsx` (+ `.test.tsx`) — Predicted/Portfolio toggle + tier-grouped company chips, extracted from today's `AlertCard`.
- `frontend/src/components/AlertDetail.tsx` (+ `.test.tsx`) — generic bottom-sheet/modal shell (mobile/desktop via CSS), content-agnostic.
- `frontend/src/components/AlertCoverCard.tsx` (+ `.test.tsx`) — full-bleed image/headline hero card, `variant: 'carousel' | 'grid'`.
- `frontend/src/components/CategoryTabs.tsx` (+ `.test.tsx`) — replaces `FeedTabs.tsx`; adds `LiveStatus` + "N new" pill + Custom-tab settings gear.
- `frontend/src/components/BottomNav.tsx` (+ `.test.tsx`) — mobile-only Feed/Holdings/Account bar.
- `frontend/src/components/MobileFeedCarousel.tsx` (+ `.test.tsx`) — scroll-snap carousel of `AlertCoverCard`s.
- `frontend/src/components/DesktopFeedGrid.tsx` (+ `.test.tsx`) — grid of `AlertCoverCard`s.

**Modified files:**
- `frontend/src/components/AlertCover.tsx` — fill-parent sizing instead of fixed `aspect-[16/9]` (only consumer becomes `AlertCoverCard`).
- `frontend/src/components/LiveStatus.tsx` — drop its own `mb-4` (caller now controls layout).
- `frontend/src/components/Feed.tsx` (+ `.test.tsx`) — rewritten: owns tab state, socket state, `openAlertId`, live-alert queueing; no longer takes an `activeTab` prop.
- `frontend/src/pages/FeedPage.tsx` (+ `.test.tsx`) — simplified to a thin wrapper around `<Feed />`.
- `frontend/src/components/NavBar.tsx` — collapses to logo-only on mobile (`md:` hides the link/account cluster).
- `frontend/src/App.tsx` (+ `.test.tsx`) — renders `<BottomNav />`; wrapper gets `pb-14 md:pb-0` so fixed bottom nav never overlaps page content.
- `frontend/src/pages/HoldingsPage.tsx`, `LoginPage.tsx`, `RegisterPage.tsx` — headline scale bump only.

**Deleted files:**
- `frontend/src/components/AlertCard.tsx` + `AlertCard.test.tsx` — superseded by `AlertCoverCard` + `AlertCompanies` + `AlertDetail`.
- `frontend/src/components/FeedTabs.tsx` + `FeedTabs.test.tsx` — superseded by `CategoryTabs`.

---

### Task 1: `AlertCompanies` — extract the company-breakdown view

**Files:**
- Create: `frontend/src/components/AlertCompanies.tsx`
- Test: `frontend/src/components/AlertCompanies.test.tsx`

**Interfaces:**
- Consumes: `Alert`, `AlertCompany` from `../lib/api`; `CompanyChip` (default export, prop `{ company: AlertCompany }`, unchanged).
- Produces: `export default function AlertCompanies({ alert, isAuthenticated }: { alert: Alert; isAuthenticated: boolean })` — rendered by `AlertDetail`'s consumer (Task 8's `Feed.tsx`) whenever a card's detail is open.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/AlertCompanies.test.tsx
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
    },
    {
      company_id: 2, ticker: 'ONGC.NS', name: 'ONGC', index_tier: 'NIFTY100',
      direction: 'bearish', magnitude_low: -3, magnitude_high: -1, rationale: 'Cost pressure.', key_points: [],
      basis: 'sector_inference', confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
    },
  ],
};

describe('AlertCompanies', () => {
  it('shows Predicted companies grouped by tier by default', () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    expect(screen.getByText('Nifty 50')).toBeInTheDocument();
    expect(screen.getByText('Nifty 100')).toBeInTheDocument();
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

  it('renders tier headings in Nifty 50 -> Nifty 100 -> Nifty 500 -> Other order', async () => {
    const tierAlert: Alert = {
      ...alert,
      companies: [
        { ...alert.companies[1], company_id: 1, name: 'Other Co', index_tier: 'SMALLCAP' },
        { ...alert.companies[1], company_id: 2, name: 'Five Hundred Co', index_tier: 'NIFTY500' },
        { ...alert.companies[0], company_id: 3, name: 'Fifty Co', index_tier: 'NIFTY50' },
        { ...alert.companies[1], company_id: 4, name: 'Hundred Co', index_tier: 'NIFTY100' },
      ],
    };
    render(<AlertCompanies alert={tierAlert} isAuthenticated />);
    const headings = screen.getAllByText(/^(Nifty 50|Nifty 100|Nifty 500|Other)$/);
    expect(headings.map((el) => el.textContent)).toEqual(['Nifty 50', 'Nifty 100', 'Nifty 500', 'Other']);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/components/AlertCompanies.test.tsx`
Expected: FAIL — `Failed to resolve import "./AlertCompanies"`.

- [ ] **Step 3: Write the implementation**

```tsx
// frontend/src/components/AlertCompanies.tsx
import { useState } from 'react';
import type { Alert, AlertCompany } from '../lib/api';
import CompanyChip from './CompanyChip';

type Tab = 'predicted' | 'my_demat';

const TIER_ORDER = ['NIFTY50', 'NIFTY100', 'NIFTY500', 'OTHER'] as const;
const TIER_LABEL: Record<string, string> = {
  NIFTY50: 'Nifty 50',
  NIFTY100: 'Nifty 100',
  NIFTY500: 'Nifty 500',
  OTHER: 'Other',
};

function tierKey(company: AlertCompany): string {
  return TIER_LABEL[company.index_tier] ? company.index_tier : 'OTHER';
}

export default function AlertCompanies({
  alert,
  isAuthenticated,
}: {
  alert: Alert;
  isAuthenticated: boolean;
}) {
  const [tab, setTab] = useState<Tab>('predicted');

  const visible = tab === 'predicted' ? alert.companies : alert.companies.filter((c) => c.in_my_holdings);

  const grouped = TIER_ORDER.map((tier) => ({
    tier,
    label: TIER_LABEL[tier],
    companies: visible.filter((c) => tierKey(c) === tier),
  })).filter((g) => g.companies.length > 0);

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
      <div className="flex gap-4">
        <button type="button" onClick={() => setTab('predicted')} className={tabClass(tab === 'predicted')}>
          Predicted
        </button>
        <button type="button" onClick={() => setTab('my_demat')} className={tabClass(tab === 'my_demat')}>
          My Portfolio
        </button>
      </div>
      {visible.length === 0 ? (
        <p className="text-xs text-muted">{emptyCopy}</p>
      ) : (
        grouped.map((group) => (
          <div key={group.tier} className="flex flex-col gap-2">
            <p className="text-xs uppercase tracking-widest text-muted">{group.label}</p>
            <div className="grid grid-cols-1 items-start gap-2 sm:grid-cols-2">
              {group.companies.map((company) => (
                <CompanyChip key={company.company_id} company={company} />
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
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AlertCompanies.tsx frontend/src/components/AlertCompanies.test.tsx
git commit -m "feat: extract AlertCompanies from AlertCard's expanded content"
```

---

### Task 2: `AlertDetail` — generic bottom-sheet/modal shell

**Files:**
- Create: `frontend/src/components/AlertDetail.tsx`
- Test: `frontend/src/components/AlertDetail.test.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone, content-agnostic — takes `children`).
- Produces: `export default function AlertDetail({ open, onClose, children }: { open: boolean; onClose: () => void; children: ReactNode })`. Used by `BottomNav` (Task 5, for the account sheet) and `Feed.tsx` (Task 8, for both the alert-detail sheet and the Custom-tab settings sheet).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/AlertDetail.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import AlertDetail from './AlertDetail';

describe('AlertDetail', () => {
  it('renders nothing when closed', () => {
    render(
      <AlertDetail open={false} onClose={() => {}}>
        <p>content</p>
      </AlertDetail>,
    );
    expect(screen.queryByText('content')).not.toBeInTheDocument();
  });

  it('renders children in a dialog when open', () => {
    render(
      <AlertDetail open onClose={() => {}}>
        <p>content</p>
      </AlertDetail>,
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('content')).toBeInTheDocument();
  });

  it('calls onClose when the close button is clicked', async () => {
    const onClose = vi.fn();
    render(
      <AlertDetail open onClose={onClose}>
        <p>content</p>
      </AlertDetail>,
    );
    await userEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it('calls onClose on backdrop click', async () => {
    const onClose = vi.fn();
    const { container } = render(
      <AlertDetail open onClose={onClose}>
        <p>content</p>
      </AlertDetail>,
    );
    const backdrop = container.querySelector('[aria-hidden="true"]');
    expect(backdrop).not.toBeNull();
    if (backdrop) await userEvent.click(backdrop);
    expect(onClose).toHaveBeenCalled();
  });

  it('calls onClose on Escape', () => {
    const onClose = vi.fn();
    render(
      <AlertDetail open onClose={onClose}>
        <p>content</p>
      </AlertDetail>,
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('moves focus into the dialog panel when opened', () => {
    render(
      <AlertDetail open onClose={() => {}}>
        <p>content</p>
      </AlertDetail>,
    );
    expect(screen.getByRole('dialog')).toHaveFocus();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/AlertDetail.test.tsx`
Expected: FAIL — `Failed to resolve import "./AlertDetail"`.

- [ ] **Step 3: Write the implementation**

```tsx
// frontend/src/components/AlertDetail.tsx
import { useEffect, useRef, type ReactNode } from 'react';

export default function AlertDetail({
  open,
  onClose,
  children,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKeyDown);
    panelRef.current?.focus();
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end md:items-center md:justify-center">
      <div
        className="absolute inset-0 bg-page/70 motion-safe:transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        className="relative z-10 max-h-[85vh] w-full overflow-y-auto rounded-t-lg border border-hairline bg-surface p-6 outline-none motion-safe:transition-transform md:max-h-[80vh] md:max-w-lg md:rounded-lg"
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute right-4 top-4 text-muted hover:text-ink"
        >
          ✕
        </button>
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/AlertDetail.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AlertDetail.tsx frontend/src/components/AlertDetail.test.tsx
git commit -m "feat: add AlertDetail generic bottom-sheet/modal shell"
```

---

### Task 3: `AlertCoverCard` — full-bleed hero card

**Files:**
- Create: `frontend/src/components/AlertCoverCard.tsx`
- Test: `frontend/src/components/AlertCoverCard.test.tsx`
- Modify: `frontend/src/components/AlertCover.tsx`

**Interfaces:**
- Consumes: `Alert` from `../lib/api`; `AlertCover` (default export, now fills its parent — see Step 1 below); `CategorySwatch` (prop `{ category: string; active?: boolean }`, unchanged); `SentimentPill` (prop `{ companies: Pick<AlertCompany,'direction'>[] }`, unchanged).
- Produces: `export default function AlertCoverCard({ alert, onOpen, variant }: { alert: Alert; onOpen: () => void; variant: 'carousel' | 'grid' })`. Used by `MobileFeedCarousel` (Task 6) and `DesktopFeedGrid` (Task 7).

- [ ] **Step 1: Modify `AlertCover` to fill its parent**

`AlertCoverCard` positions `AlertCover` as an absolutely-positioned full-bleed background, so it must fill its container instead of imposing its own `aspect-[16/9]` (that fixed-ratio behavior was only needed for the old `AlertCard`, which this redesign deletes in Task 11).

In `frontend/src/components/AlertCover.tsx`, replace both occurrences of `aspect-[16/9] w-full` with `h-full w-full`:

```tsx
// frontend/src/components/AlertCover.tsx (full file after the change)
import { useState } from 'react';

// Full static class strings (not built by interpolation) so Tailwind's content
// scanner keeps them -- same convention as CategorySwatch's SWATCH_CLASS.
const COVER_BG: Record<string, string> = {
  oil_energy: 'bg-swatch-oil_energy/10',
  banking: 'bg-swatch-banking/10',
  auto_ev: 'bg-swatch-auto_ev/10',
  geopolitics: 'bg-swatch-geopolitics/10',
};
const COVER_BG_FALLBACK = 'bg-swatch-other/10';

const GLYPH_BG: Record<string, string> = {
  oil_energy: 'bg-swatch-oil_energy',
  banking: 'bg-swatch-banking',
  auto_ev: 'bg-swatch-auto_ev',
  geopolitics: 'bg-swatch-geopolitics',
};
const GLYPH_BG_FALLBACK = 'bg-swatch-other';

// No real photo -- either the article's page had no og:image, or the scrape
// hasn't run for it yet. A quiet category-tinted cover keeps every card
// visually anchored instead of leaving a blank gap where a photo would go.
function CategoryCover({ category }: { category: string }) {
  const bgClass = COVER_BG[category] ?? COVER_BG_FALLBACK;
  const glyphClass = GLYPH_BG[category] ?? GLYPH_BG_FALLBACK;
  return (
    <div className={`flex h-full w-full items-center justify-center ${bgClass}`}>
      <span className={`h-10 w-10 rounded-full ${glyphClass} opacity-40`} aria-hidden="true" />
    </div>
  );
}

export default function AlertCover({ imageUrl, category }: { imageUrl: string | null; category: string }) {
  const [failed, setFailed] = useState(false);

  if (!imageUrl || failed) {
    return <CategoryCover category={category} />;
  }

  return (
    <img
      src={imageUrl}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className="h-full w-full object-cover"
    />
  );
}
```

- [ ] **Step 2: Run the existing AlertCover tests to confirm they still pass**

Run: `npx vitest run src/components/AlertCover.test.tsx`
Expected: PASS (3 tests — none assert on the aspect-ratio class, only `src`/fallback presence).

- [ ] **Step 3: Write the failing test for AlertCoverCard**

```tsx
// frontend/src/components/AlertCoverCard.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import AlertCoverCard from './AlertCoverCard';
import type { Alert } from '../lib/api';

const alert: Alert = {
  id: 1,
  category: 'oil_energy',
  created_at: '2026-07-09T10:00:00+00:00',
  article: { id: 1, title: 'US strikes Iran oil export sites', url: 'https://example.com/a', image_url: 'https://example.com/pic.jpg' },
  companies: [
    {
      company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance Industries', index_tier: 'NIFTY50',
      direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'x', key_points: [],
      basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
    },
  ],
};

describe('AlertCoverCard', () => {
  it('renders the headline, category, and sentiment', () => {
    render(<AlertCoverCard alert={alert} onOpen={() => {}} variant="carousel" />);
    expect(screen.getByText('US strikes Iran oil export sites')).toBeInTheDocument();
    expect(screen.getByText('Oil & Energy')).toBeInTheDocument();
    expect(screen.getByText('Net Bullish')).toBeInTheDocument();
  });

  it('calls onOpen when clicked', async () => {
    const onOpen = vi.fn();
    render(<AlertCoverCard alert={alert} onOpen={onOpen} variant="carousel" />);
    await userEvent.click(screen.getByRole('button', { name: /us strikes iran/i }));
    expect(onOpen).toHaveBeenCalled();
  });

  it('calls onOpen on Enter when focused', async () => {
    const onOpen = vi.fn();
    render(<AlertCoverCard alert={alert} onOpen={onOpen} variant="grid" />);
    const card = screen.getByRole('button', { name: /us strikes iran/i });
    card.focus();
    await userEvent.keyboard('{Enter}');
    expect(onOpen).toHaveBeenCalled();
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `npx vitest run src/components/AlertCoverCard.test.tsx`
Expected: FAIL — `Failed to resolve import "./AlertCoverCard"`.

- [ ] **Step 5: Write the implementation**

```tsx
// frontend/src/components/AlertCoverCard.tsx
import type { KeyboardEvent } from 'react';
import type { Alert } from '../lib/api';
import AlertCover from './AlertCover';
import CategorySwatch from './CategorySwatch';
import SentimentPill from './SentimentPill';

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

// carousel: one card fills the mobile scroll-snap viewport (see MobileFeedCarousel).
// grid: a fixed-aspect tile inside the desktop grid (see DesktopFeedGrid).
const SIZE_CLASS: Record<'carousel' | 'grid', string> = {
  carousel: 'h-full snap-start',
  grid: 'aspect-[3/4] rounded-lg',
};

export default function AlertCoverCard({
  alert,
  onOpen,
  variant,
}: {
  alert: Alert;
  onOpen: () => void;
  variant: 'carousel' | 'grid';
}) {
  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onOpen();
    }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={onKeyDown}
      className={`relative w-full shrink-0 cursor-pointer overflow-hidden ${SIZE_CLASS[variant]}`}
    >
      <div className="absolute inset-0">
        <AlertCover imageUrl={alert.article.image_url} category={alert.category} />
      </div>
      <div
        className="absolute inset-0 bg-gradient-to-t from-page/95 via-page/40 to-transparent"
        aria-hidden="true"
      />
      <div className="absolute inset-x-0 top-0 flex items-center justify-between p-4">
        <CategorySwatch category={alert.category} active />
        <time className="text-xs uppercase tracking-widest text-ink/80">{formatTime(alert.created_at)}</time>
      </div>
      <div className="absolute inset-x-0 bottom-0 flex flex-col gap-3 p-4">
        <h2 className="font-display text-2xl font-bold leading-snug text-ink drop-shadow-sm">
          {alert.article.title}
        </h2>
        <SentimentPill companies={alert.companies} />
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `npx vitest run src/components/AlertCoverCard.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/AlertCover.tsx frontend/src/components/AlertCoverCard.tsx frontend/src/components/AlertCoverCard.test.tsx
git commit -m "feat: add AlertCoverCard full-bleed hero card"
```

---

### Task 4: `CategoryTabs` — replaces `FeedTabs`, carries `LiveStatus` + "N new" + settings gear

**Files:**
- Create: `frontend/src/components/CategoryTabs.tsx`
- Test: `frontend/src/components/CategoryTabs.test.tsx`
- Modify: `frontend/src/components/LiveStatus.tsx`

**Interfaces:**
- Consumes: `LiveStatus` (default export, prop `{ connected: boolean; lastAlertAt: string | null }`, modified below).
- Produces: `export type FeedTab = 'india' | 'global' | 'custom'` and `export default function CategoryTabs({ active, onChange, connected, lastAlertAt, newCount, onRevealNew, onOpenCustomSettings }: { active: FeedTab; onChange: (tab: FeedTab) => void; connected: boolean; lastAlertAt: string | null; newCount: number; onRevealNew: () => void; onOpenCustomSettings: () => void })`. Used by `Feed.tsx` (Task 8).

- [ ] **Step 1: Modify `LiveStatus` to drop its own margin**

`LiveStatus` used to be a standalone block above the feed (hence its own `mb-4`). It now sits inline inside `CategoryTabs`'s row, so layout spacing is the caller's job.

In `frontend/src/components/LiveStatus.tsx`, change the root `<div>`'s className from `"mb-4 flex items-center gap-2 text-xs uppercase tracking-widest"` to `"flex items-center gap-2 text-xs uppercase tracking-widest"`.

- [ ] **Step 2: Run the existing LiveStatus tests to confirm they still pass**

Run: `npx vitest run src/components/LiveStatus.test.tsx`
Expected: PASS (2 tests — no assertion on `mb-4`).

- [ ] **Step 3: Write the failing test for CategoryTabs**

```tsx
// frontend/src/components/CategoryTabs.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import CategoryTabs from './CategoryTabs';

function renderTabs(overrides: Partial<Parameters<typeof CategoryTabs>[0]> = {}) {
  return render(
    <CategoryTabs
      active="india"
      onChange={() => {}}
      connected
      lastAlertAt={null}
      newCount={0}
      onRevealNew={() => {}}
      onOpenCustomSettings={() => {}}
      {...overrides}
    />,
  );
}

describe('CategoryTabs', () => {
  it('renders all three tabs and marks the active one selected', () => {
    renderTabs({ active: 'global' });
    expect(screen.getByRole('tab', { name: /global/i })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: /india/i })).toHaveAttribute('aria-selected', 'false');
  });

  it('calls onChange with the tab key when a tab is clicked', async () => {
    const onChange = vi.fn();
    renderTabs({ onChange });
    await userEvent.click(screen.getByRole('tab', { name: /custom/i }));
    expect(onChange).toHaveBeenCalledWith('custom');
  });

  it('shows the Live status', () => {
    renderTabs({ connected: true });
    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('shows an "N new" pill only when newCount > 0, and it calls onRevealNew', async () => {
    const onRevealNew = vi.fn();
    const { rerender } = renderTabs({ newCount: 0, onRevealNew });
    expect(screen.queryByText(/new/i)).not.toBeInTheDocument();
    rerender(
      <CategoryTabs
        active="india"
        onChange={() => {}}
        connected
        lastAlertAt={null}
        newCount={3}
        onRevealNew={onRevealNew}
        onOpenCustomSettings={() => {}}
      />,
    );
    const pill = screen.getByText('3 new');
    await userEvent.click(pill);
    expect(onRevealNew).toHaveBeenCalled();
  });

  it('shows the settings gear only on the Custom tab', () => {
    const { rerender } = renderTabs({ active: 'india' });
    expect(screen.queryByLabelText(/custom feed settings/i)).not.toBeInTheDocument();
    rerender(
      <CategoryTabs
        active="custom"
        onChange={() => {}}
        connected
        lastAlertAt={null}
        newCount={0}
        onRevealNew={() => {}}
        onOpenCustomSettings={() => {}}
      />,
    );
    expect(screen.getByLabelText(/custom feed settings/i)).toBeInTheDocument();
  });

  it('calls onOpenCustomSettings when the gear is clicked', async () => {
    const onOpenCustomSettings = vi.fn();
    renderTabs({ active: 'custom', onOpenCustomSettings });
    await userEvent.click(screen.getByLabelText(/custom feed settings/i));
    expect(onOpenCustomSettings).toHaveBeenCalled();
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `npx vitest run src/components/CategoryTabs.test.tsx`
Expected: FAIL — `Failed to resolve import "./CategoryTabs"`.

- [ ] **Step 5: Write the implementation**

```tsx
// frontend/src/components/CategoryTabs.tsx
import LiveStatus from './LiveStatus';

export type FeedTab = 'india' | 'global' | 'custom';

const TABS: { key: FeedTab; label: string }[] = [
  { key: 'india', label: 'India' },
  { key: 'global', label: 'Global' },
  { key: 'custom', label: 'Custom' },
];

export default function CategoryTabs({
  active,
  onChange,
  connected,
  lastAlertAt,
  newCount,
  onRevealNew,
  onOpenCustomSettings,
}: {
  active: FeedTab;
  onChange: (tab: FeedTab) => void;
  connected: boolean;
  lastAlertAt: string | null;
  newCount: number;
  onRevealNew: () => void;
  onOpenCustomSettings: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-hairline">
      <div className="flex gap-6" role="tablist" aria-label="Feed markets">
        {TABS.map((t) => {
          const isActive = t.key === active;
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => onChange(t.key)}
              className={`border-b-2 pb-3 text-base font-bold uppercase tracking-widest motion-safe:transition-colors ${
                isActive ? 'border-ink text-ink' : 'border-transparent text-muted hover:text-ink'
              }`}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      <div className="flex items-center gap-3 pb-3">
        {newCount > 0 && (
          <button
            type="button"
            onClick={onRevealNew}
            className="rounded-full border-[1.5px] border-bullish px-3 py-1 text-xs uppercase tracking-widest text-bullish"
          >
            {newCount} new
          </button>
        )}
        <LiveStatus connected={connected} lastAlertAt={lastAlertAt} />
        {active === 'custom' && (
          <button
            type="button"
            onClick={onOpenCustomSettings}
            aria-label="Custom feed settings"
            className="text-muted hover:text-ink"
          >
            ⚙
          </button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `npx vitest run src/components/CategoryTabs.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/LiveStatus.tsx frontend/src/components/CategoryTabs.tsx frontend/src/components/CategoryTabs.test.tsx
git commit -m "feat: add CategoryTabs (replaces FeedTabs), carrying LiveStatus and new-alerts pill"
```

---

### Task 5: `BottomNav` — mobile Feed/Holdings/Account bar

**Files:**
- Create: `frontend/src/components/BottomNav.tsx`
- Test: `frontend/src/components/BottomNav.test.tsx`

**Interfaces:**
- Consumes: `useAuth` from `../lib/auth` (`{ token, email, logout }`, unchanged); `AlertDetail` from `./AlertDetail` (Task 2).
- Produces: `export default function BottomNav()`. Rendered once in `App.tsx` (Task 9).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/BottomNav.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import BottomNav from './BottomNav';
import { AuthProvider } from '../lib/auth';

function renderNav(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <BottomNav />
      </AuthProvider>
    </MemoryRouter>,
  );
}

function setToken() {
  localStorage.setItem('newsflo.token', 'tok');
  localStorage.setItem('newsflo.email', 'a@example.com');
}

afterEach(() => {
  localStorage.clear();
});

describe('BottomNav', () => {
  it('renders Feed and Holdings links', () => {
    renderNav();
    expect(screen.getByRole('link', { name: /^feed$/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /^holdings$/i })).toBeInTheDocument();
  });

  it('links Account to /login when logged out', () => {
    renderNav();
    expect(screen.getByRole('link', { name: /account/i })).toHaveAttribute('href', '/login');
  });

  it('opens an account sheet with email and Logout when logged in', async () => {
    setToken();
    renderNav();
    await userEvent.click(screen.getByRole('button', { name: /account/i }));
    expect(screen.getByText('a@example.com')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /logout/i })).toBeInTheDocument();
  });

  it('calls logout and closes the sheet when Logout is clicked', async () => {
    setToken();
    renderNav();
    await userEvent.click(screen.getByRole('button', { name: /account/i }));
    await userEvent.click(screen.getByRole('button', { name: /logout/i }));
    expect(screen.queryByText('a@example.com')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/BottomNav.test.tsx`
Expected: FAIL — `Failed to resolve import "./BottomNav"`.

- [ ] **Step 3: Write the implementation**

```tsx
// frontend/src/components/BottomNav.tsx
import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import AlertDetail from './AlertDetail';

const LINKS = [
  { to: '/', label: 'Feed' },
  { to: '/holdings', label: 'Holdings' },
];

export default function BottomNav() {
  const { pathname } = useLocation();
  const { token, email, logout } = useAuth();
  const [accountOpen, setAccountOpen] = useState(false);

  const itemClass = (activeCondition: boolean) =>
    `flex flex-1 items-center justify-center text-xs uppercase tracking-widest ${
      activeCondition ? 'text-ink' : 'text-muted'
    }`;

  return (
    <>
      <nav className="fixed inset-x-0 bottom-0 z-40 flex h-14 border-t border-hairline bg-page md:hidden">
        {LINKS.map((l) => (
          <Link key={l.to} to={l.to} className={itemClass(pathname === l.to)}>
            {l.label}
          </Link>
        ))}
        {token ? (
          <button type="button" onClick={() => setAccountOpen(true)} className={itemClass(accountOpen)}>
            Account
          </button>
        ) : (
          <Link to="/login" className={itemClass(pathname === '/login')}>
            Account
          </Link>
        )}
      </nav>
      <AlertDetail open={accountOpen} onClose={() => setAccountOpen(false)}>
        <div className="flex flex-col gap-4">
          <p className="text-xs uppercase tracking-widest text-muted">{email}</p>
          <button
            type="button"
            onClick={() => {
              logout();
              setAccountOpen(false);
            }}
            className="self-start rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink"
          >
            Logout
          </button>
        </div>
      </AlertDetail>
    </>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/BottomNav.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BottomNav.tsx frontend/src/components/BottomNav.test.tsx
git commit -m "feat: add BottomNav mobile Feed/Holdings/Account bar"
```

---

### Task 6: `MobileFeedCarousel`

**Files:**
- Create: `frontend/src/components/MobileFeedCarousel.tsx`
- Test: `frontend/src/components/MobileFeedCarousel.test.tsx`

**Interfaces:**
- Consumes: `Alert` from `../lib/api`; `AlertCoverCard` from `./AlertCoverCard` (Task 3).
- Produces: `export default function MobileFeedCarousel({ alerts, onOpen }: { alerts: Alert[]; onOpen: (alertId: number) => void })`. Used by `Feed.tsx` (Task 8).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/MobileFeedCarousel.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import MobileFeedCarousel from './MobileFeedCarousel';
import type { Alert } from '../lib/api';

function makeAlert(id: number, title: string): Alert {
  return {
    id,
    category: 'oil_energy',
    created_at: '2026-07-09T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}`, image_url: null },
    companies: [],
  };
}

describe('MobileFeedCarousel', () => {
  it('renders one card per alert', () => {
    render(<MobileFeedCarousel alerts={[makeAlert(1, 'First'), makeAlert(2, 'Second')]} onOpen={() => {}} />);
    expect(screen.getByText('First')).toBeInTheDocument();
    expect(screen.getByText('Second')).toBeInTheDocument();
  });

  it('calls onOpen with the alert id when a card is clicked', async () => {
    const onOpen = vi.fn();
    render(<MobileFeedCarousel alerts={[makeAlert(7, 'Seventh')]} onOpen={onOpen} />);
    await userEvent.click(screen.getByRole('button', { name: /seventh/i }));
    expect(onOpen).toHaveBeenCalledWith(7);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/MobileFeedCarousel.test.tsx`
Expected: FAIL — `Failed to resolve import "./MobileFeedCarousel"`.

- [ ] **Step 3: Write the implementation**

```tsx
// frontend/src/components/MobileFeedCarousel.tsx
import type { Alert } from '../lib/api';
import AlertCoverCard from './AlertCoverCard';

export default function MobileFeedCarousel({
  alerts,
  onOpen,
}: {
  alerts: Alert[];
  onOpen: (alertId: number) => void;
}) {
  return (
    <div className="h-full min-h-0 flex-1 snap-y snap-mandatory overflow-y-auto md:hidden">
      {alerts.map((alert) => (
        <AlertCoverCard key={alert.id} alert={alert} variant="carousel" onOpen={() => onOpen(alert.id)} />
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/MobileFeedCarousel.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MobileFeedCarousel.tsx frontend/src/components/MobileFeedCarousel.test.tsx
git commit -m "feat: add MobileFeedCarousel scroll-snap container"
```

---

### Task 7: `DesktopFeedGrid`

**Files:**
- Create: `frontend/src/components/DesktopFeedGrid.tsx`
- Test: `frontend/src/components/DesktopFeedGrid.test.tsx`

**Interfaces:**
- Consumes: `Alert` from `../lib/api`; `AlertCoverCard` from `./AlertCoverCard` (Task 3).
- Produces: `export default function DesktopFeedGrid({ alerts, onOpen }: { alerts: Alert[]; onOpen: (alertId: number) => void })`. Used by `Feed.tsx` (Task 8).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/DesktopFeedGrid.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import DesktopFeedGrid from './DesktopFeedGrid';
import type { Alert } from '../lib/api';

function makeAlert(id: number, title: string): Alert {
  return {
    id,
    category: 'oil_energy',
    created_at: '2026-07-09T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}`, image_url: null },
    companies: [],
  };
}

describe('DesktopFeedGrid', () => {
  it('renders one card per alert', () => {
    render(<DesktopFeedGrid alerts={[makeAlert(1, 'First'), makeAlert(2, 'Second')]} onOpen={() => {}} />);
    expect(screen.getByText('First')).toBeInTheDocument();
    expect(screen.getByText('Second')).toBeInTheDocument();
  });

  it('calls onOpen with the alert id when a card is clicked', async () => {
    const onOpen = vi.fn();
    render(<DesktopFeedGrid alerts={[makeAlert(7, 'Seventh')]} onOpen={onOpen} />);
    await userEvent.click(screen.getByRole('button', { name: /seventh/i }));
    expect(onOpen).toHaveBeenCalledWith(7);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/DesktopFeedGrid.test.tsx`
Expected: FAIL — `Failed to resolve import "./DesktopFeedGrid"`.

- [ ] **Step 3: Write the implementation**

```tsx
// frontend/src/components/DesktopFeedGrid.tsx
import type { Alert } from '../lib/api';
import AlertCoverCard from './AlertCoverCard';

export default function DesktopFeedGrid({
  alerts,
  onOpen,
}: {
  alerts: Alert[];
  onOpen: (alertId: number) => void;
}) {
  return (
    <div className="hidden gap-4 py-6 md:grid md:grid-cols-2 lg:grid-cols-3">
      {alerts.map((alert) => (
        <AlertCoverCard key={alert.id} alert={alert} variant="grid" onOpen={() => onOpen(alert.id)} />
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/DesktopFeedGrid.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DesktopFeedGrid.tsx frontend/src/components/DesktopFeedGrid.test.tsx
git commit -m "feat: add DesktopFeedGrid card grid container"
```

---

### Task 8: Rewrite `Feed.tsx` and simplify `FeedPage.tsx`

**Files:**
- Modify: `frontend/src/components/Feed.tsx` (full rewrite)
- Modify: `frontend/src/components/Feed.test.tsx` (full rewrite)
- Modify: `frontend/src/pages/FeedPage.tsx`
- Modify: `frontend/src/pages/FeedPage.test.tsx`

**Interfaces:**
- Consumes: `AlertCompanies` (Task 1), `AlertDetail` (Task 2), `CategoryTabs`/`FeedTab` (Task 4), `MobileFeedCarousel` (Task 6), `DesktopFeedGrid` (Task 7), `WatchlistSettings` (unchanged), `useAlertsSocket` (unchanged, returns `{ alerts, connected }`), `getAlerts`/`getWatchlist` (unchanged).
- Produces: `export default function Feed()` — **no longer takes an `activeTab` prop**; it owns tab state internally now. `export function mergeAlerts(live: Alert[], fetched: Alert[]): Alert[]` stays exported unchanged (existing logic, unit-tested directly).

- [ ] **Step 1: Write the failing test**

This replaces `Feed.test.tsx` entirely — the old file tested `<Feed activeTab="india" />`, which no longer exists as a prop.

```tsx
// frontend/src/components/Feed.test.tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Feed, { mergeAlerts } from './Feed';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';
import type { Alert, AlertCompany } from '../lib/api';

// Isolate Feed from the real socket in most tests; individual tests override
// this via vi.mocked(useAlertsSocket).mockReturnValue(...) where needed.
vi.mock('../lib/useAlertsSocket', () => ({ useAlertsSocket: vi.fn(() => ({ alerts: [], connected: true })) }));
import { useAlertsSocket } from '../lib/useAlertsSocket';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1,
    ticker: 'RELIANCE.NS',
    name: 'Reliance',
    index_tier: 'NIFTY50',
    direction: 'bullish',
    magnitude_low: 1,
    magnitude_high: 2,
    rationale: 'x',
    key_points: [],
    basis: 'direct_mention',
    confidence: 'llm_estimate',
    market: 'IN',
    in_my_holdings: false,
    past_mentions: [],
    ...overrides,
  };
}

function makeAlert(id: number, title: string, companies: AlertCompany[], category = 'oil_energy'): Alert {
  return {
    id,
    category,
    created_at: '2026-07-10T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}`, image_url: null },
    companies,
  };
}

function renderFeed() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Feed />
      </AuthProvider>
    </MemoryRouter>,
  );
}

function setToken() {
  localStorage.setItem('newsflo.token', 'tok');
  localStorage.setItem('newsflo.email', 'a@example.com');
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.mocked(useAlertsSocket).mockReturnValue({ alerts: [], connected: true });
  localStorage.clear();
});

describe('mergeAlerts', () => {
  it('prepends live alerts and dedupes by id (fetched data wins on collision)', () => {
    const merged = mergeAlerts([makeAlert(2, 'two-live', [])], [makeAlert(1, 'one', []), makeAlert(2, 'two', [])]);
    expect(merged.map((a) => a.id)).toEqual([2, 1]);
    expect(merged[0].article.title).toBe('two');
  });
});

describe('Feed', () => {
  const indiaAlert = makeAlert(1, 'India oil headline', [company({ market: 'IN' })]);
  const globalAlert = makeAlert(2, 'Global tech headline', [
    company({ company_id: 2, ticker: 'AAPL', name: 'Apple', market: 'GLOBAL' }),
  ], 'it');

  it('defaults to the India tab and switches to Global on click', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert, globalAlert]);
    renderFeed();
    expect(await screen.findByText('India oil headline')).toBeInTheDocument();
    expect(screen.queryByText('Global tech headline')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: /global/i }));
    expect(await screen.findByText('Global tech headline')).toBeInTheDocument();
    expect(screen.queryByText('India oil headline')).not.toBeInTheDocument();
  });

  it('opens AlertDetail with the company breakdown when a card is clicked', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    renderFeed();
    await screen.findByText('India oil headline');
    // Both the mobile carousel and desktop grid render a card for this alert
    // (CSS toggles which is visible; jsdom doesn't evaluate media queries),
    // so there are two matching buttons -- click the first.
    const cards = screen.getAllByRole('button', { name: /india oil headline/i });
    await userEvent.click(cards[0]);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Reliance')).toBeInTheDocument();
  });

  it('Custom tab shows a login prompt when logged out', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    renderFeed();
    await userEvent.click(screen.getByRole('tab', { name: /custom/i }));
    expect(await screen.findByText(/log in to build your custom feed/i)).toBeInTheDocument();
  });

  it('Custom tab settings gear opens the filter editor in a sheet', async () => {
    setToken();
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ categories: [], companies: [] });
    vi.spyOn(api, 'getCategories').mockResolvedValue([]);
    vi.spyOn(api, 'getCompanies').mockResolvedValue([]);
    renderFeed();
    await userEvent.click(screen.getByRole('tab', { name: /custom/i }));
    await userEvent.click(await screen.findByLabelText(/custom feed settings/i));
    expect(await screen.findByRole('button', { name: /save/i })).toBeInTheDocument();
  });

  it('queues a live-pushed alert as "N new" instead of splicing it in immediately', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    vi.mocked(useAlertsSocket).mockReturnValue({ alerts: [], connected: true });
    const { rerender } = renderFeed();
    await screen.findByText('India oil headline');

    const liveAlert = makeAlert(3, 'Live oil headline', [company({ company_id: 3, market: 'IN' })]);
    vi.mocked(useAlertsSocket).mockReturnValue({ alerts: [liveAlert], connected: true });
    rerender(
      <MemoryRouter>
        <AuthProvider>
          <Feed />
        </AuthProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText('1 new')).toBeInTheDocument();
    expect(screen.queryByText('Live oil headline')).not.toBeInTheDocument();

    await userEvent.click(screen.getByText('1 new'));
    expect(await screen.findByText('Live oil headline')).toBeInTheDocument();
    expect(screen.queryByText('1 new')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/Feed.test.tsx`
Expected: FAIL — old `Feed.tsx` still requires an `activeTab` prop and has none of this new behavior.

- [ ] **Step 3: Write the implementation**

```tsx
// frontend/src/components/Feed.tsx
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { getAlerts, getWatchlist, type Alert, type Watchlist } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useAlertsSocket } from '../lib/useAlertsSocket';
import { alertMatchesMarket, alertMatchesWatchlist } from '../lib/feedFilters';
import AlertCompanies from './AlertCompanies';
import AlertDetail from './AlertDetail';
import CategoryTabs, { type FeedTab } from './CategoryTabs';
import DesktopFeedGrid from './DesktopFeedGrid';
import MobileFeedCarousel from './MobileFeedCarousel';
import WatchlistSettings from './WatchlistSettings';

// Prepend live pushes ahead of the fetched list, deduping by id. On an id
// collision the `fetched` copy's data wins: REST-fetched alerts carry the
// accurate per-viewer `in_my_holdings` flag, while live WS-pushed payloads
// always report `in_my_holdings: false` (the pipeline has no per-viewer
// context at broadcast time). Live entries only contribute brand-new ids
// (and their own data) that aren't yet present in `fetched`, so a fresh
// push still appears immediately at the top of the feed.
export function mergeAlerts(live: Alert[], fetched: Alert[]): Alert[] {
  const fetchedById = new Map(fetched.map((alert) => [alert.id, alert]));
  const seen = new Set<number>();
  const merged: Alert[] = [];
  for (const alert of [...live, ...fetched]) {
    if (seen.has(alert.id)) continue;
    seen.add(alert.id);
    merged.push(fetchedById.get(alert.id) ?? alert);
  }
  return merged;
}

const EMPTY_WATCHLIST: Watchlist = { categories: [], companies: [] };

export default function Feed() {
  const { token } = useAuth();
  const [tab, setTab] = useState<FeedTab>('india');
  const [fetched, setFetched] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [watchlist, setWatchlist] = useState<Watchlist>(EMPTY_WATCHLIST);
  const [openAlertId, setOpenAlertId] = useState<number | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Ids the user has already been shown. Live pushes not yet in this set are
  // "new" and held back from the rendered list (see design spec: a card
  // arriving mid-scroll must never shift the user's scroll-snap position).
  const [revealedIds, setRevealedIds] = useState<Set<number>>(new Set());
  const { alerts: live, connected } = useAlertsSocket();

  useEffect(() => {
    let active = true;
    setLoading(true);
    getAlerts(token)
      .then((data) => {
        if (active) {
          setFetched(data);
          setRevealedIds(new Set(data.map((a) => a.id)));
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'Failed to load alerts.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [token]);

  const refreshWatchlist = useCallback(() => {
    if (!token) return;
    getWatchlist(token)
      .then(setWatchlist)
      .catch(() => setWatchlist(EMPTY_WATCHLIST));
  }, [token]);

  useEffect(() => {
    if (tab === 'custom' && token) {
      refreshWatchlist();
    }
  }, [tab, token, refreshWatchlist]);

  const alerts = useMemo(() => mergeAlerts(live, fetched), [live, fetched]);

  const newCount = useMemo(
    () => alerts.filter((a) => !revealedIds.has(a.id)).length,
    [alerts, revealedIds],
  );
  const shownAlerts = useMemo(
    () => alerts.filter((a) => revealedIds.has(a.id)),
    [alerts, revealedIds],
  );
  const revealNew = useCallback(() => {
    setRevealedIds(new Set(alerts.map((a) => a.id)));
  }, [alerts]);

  const visibleAlerts = useMemo(() => {
    if (tab === 'india') return shownAlerts.filter((a) => alertMatchesMarket(a, 'IN'));
    if (tab === 'global') return shownAlerts.filter((a) => alertMatchesMarket(a, 'GLOBAL'));
    return shownAlerts.filter((a) => alertMatchesWatchlist(a, watchlist));
  }, [shownAlerts, tab, watchlist]);

  const openAlert = alerts.find((a) => a.id === openAlertId) ?? null;
  const customConfigured = watchlist.categories.length > 0 || watchlist.companies.length > 0;

  let body: ReactNode;
  if (loading) {
    body = <p className="p-4 text-xs uppercase tracking-widest text-muted">Loading…</p>;
  } else if (error) {
    body = <p className="p-4 text-xs uppercase tracking-widest text-bearish">{error}</p>;
  } else if (tab === 'custom' && !token) {
    body = (
      <p className="p-4 text-xs uppercase tracking-widest text-muted">
        Log in to build your custom feed.{' '}
        <Link to="/login" className="text-ink underline">
          Log in
        </Link>
      </p>
    );
  } else if (tab === 'custom' && !customConfigured) {
    body = (
      <p className="p-4 text-xs uppercase tracking-widest text-muted">
        Choose categories or companies to build your custom feed.
      </p>
    );
  } else if (visibleAlerts.length === 0) {
    const emptyMessage =
      tab === 'custom'
        ? 'No alerts match your custom filters yet.'
        : `No ${tab === 'india' ? 'India' : 'Global'} alerts yet. New stories will appear here live.`;
    body = <p className="p-4 text-xs uppercase tracking-widest text-muted">{emptyMessage}</p>;
  } else {
    body = (
      <>
        <MobileFeedCarousel alerts={visibleAlerts} onOpen={setOpenAlertId} />
        <DesktopFeedGrid alerts={visibleAlerts} onOpen={setOpenAlertId} />
      </>
    );
  }

  return (
    // Mobile: a fixed-height column (100dvh minus the 3.5rem slim NavBar and
    // 3.5rem BottomNav, both h-14 -- see NavBar.tsx/BottomNav.tsx) so the
    // carousel's flex-1 child can fill exactly the remaining space. Desktop
    // drops the fixed height entirely and scrolls normally with the page.
    <div className="flex h-[calc(100dvh-7rem)] flex-col overflow-hidden md:h-auto md:overflow-visible">
      <div className="px-4 pt-4 md:mx-auto md:w-full md:max-w-feed md:px-4 md:pt-8">
        <CategoryTabs
          active={tab}
          onChange={setTab}
          connected={connected}
          lastAlertAt={shownAlerts[0]?.created_at ?? null}
          newCount={newCount}
          onRevealNew={revealNew}
          onOpenCustomSettings={() => setSettingsOpen(true)}
        />
      </div>
      <div className="min-h-0 flex-1 md:mx-auto md:w-full md:max-w-feed md:px-4">{body}</div>
      <AlertDetail open={openAlertId !== null} onClose={() => setOpenAlertId(null)}>
        {openAlert && <AlertCompanies alert={openAlert} isAuthenticated={token !== null} />}
      </AlertDetail>
      <AlertDetail open={settingsOpen} onClose={() => setSettingsOpen(false)}>
        <WatchlistSettings
          onSaved={() => {
            refreshWatchlist();
            setSettingsOpen(false);
          }}
        />
      </AlertDetail>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/Feed.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Update `FeedPage.tsx` to a thin wrapper**

```tsx
// frontend/src/pages/FeedPage.tsx
import Feed from '../components/Feed';

export default function FeedPage() {
  return <Feed />;
}
```

- [ ] **Step 6: Update `FeedPage.test.tsx`**

The India/Global-switching behavior is now fully covered by `Feed.test.tsx` (Step 1 above, which renders `<Feed />` the same way `<FeedPage />` does). Replace `FeedPage.test.tsx` with a minimal smoke test:

```tsx
// frontend/src/pages/FeedPage.test.tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import FeedPage from './FeedPage';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';

vi.mock('../lib/useAlertsSocket', () => ({ useAlertsSocket: () => ({ alerts: [], connected: true }) }));

afterEach(() => {
  vi.restoreAllMocks();
});

describe('FeedPage', () => {
  it('renders the feed with category tabs', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([]);
    render(
      <MemoryRouter>
        <AuthProvider>
          <FeedPage />
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByRole('tab', { name: /india/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 7: Run both test files to verify they pass**

Run: `npx vitest run src/components/Feed.test.tsx src/pages/FeedPage.test.tsx`
Expected: PASS (7 tests total).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Feed.tsx frontend/src/components/Feed.test.tsx frontend/src/pages/FeedPage.tsx frontend/src/pages/FeedPage.test.tsx
git commit -m "feat: rewrite Feed as the Inshorts-style carousel/grid owner, simplify FeedPage"
```

---

### Task 9: Wire `BottomNav` into `App.tsx`, collapse `NavBar` on mobile

**Files:**
- Modify: `frontend/src/components/NavBar.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `BottomNav` from `./components/BottomNav` (Task 5).
- Produces: no new exports — `NavBar` and `App` keep their existing default-export signatures.

- [ ] **Step 1: Modify `NavBar.tsx` to collapse to logo-only on mobile**

`BottomNav` now owns Feed/Holdings/Account navigation on mobile, so the top bar only needs the logo there; the full link/account cluster stays for desktop (`md:flex`).

```tsx
// frontend/src/components/NavBar.tsx
import { Link } from 'react-router-dom';
import { useAuth } from '../lib/auth';

export default function NavBar() {
  const { token, email, logout } = useAuth();
  return (
    <nav className="border-b border-hairline bg-page">
      <div className="mx-auto flex h-14 max-w-feed items-center px-4 md:h-auto md:justify-between md:py-4">
        <Link to="/" className="font-display text-lg font-bold text-ink">
          NewsFlo
        </Link>
        <div className="hidden items-center gap-6 md:flex">
          <Link to="/" className="text-xs uppercase tracking-widest text-muted hover:text-ink">
            Feed
          </Link>
          <Link to="/holdings" className="text-xs uppercase tracking-widest text-muted hover:text-ink">
            Holdings
          </Link>
        </div>
        <div className="hidden items-center gap-4 text-xs uppercase tracking-widest md:flex">
          {token ? (
            <>
              <span className="text-muted">{email}</span>
              <button type="button" onClick={logout} className="text-ink hover:text-muted">
                Logout
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="text-ink hover:text-muted">
                Login
              </Link>
              <Link to="/register" className="text-ink hover:text-muted">
                Register
              </Link>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
```

(This only changes the wrapping `<div>`'s className and adds `hidden md:flex` to the two link clusters — every link/button jsdom can already find stays in the DOM, so `NavBar.test.tsx` needs no changes.)

- [ ] **Step 2: Run the existing NavBar tests to confirm they still pass**

Run: `npx vitest run src/components/NavBar.test.tsx`
Expected: PASS (no changes needed — jsdom doesn't evaluate `md:` media queries, so every link is still queryable).

- [ ] **Step 3: Modify `App.tsx` to render `BottomNav` and reserve space for it**

```tsx
// frontend/src/App.tsx
import { Navigate, Route, Routes } from 'react-router-dom';
import type { ReactElement } from 'react';
import BottomNav from './components/BottomNav';
import NavBar from './components/NavBar';
import FeedPage from './pages/FeedPage';
import HoldingsPage from './pages/HoldingsPage';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import { useAuth } from './lib/auth';

function RequireAuth({ children }: { children: ReactElement }) {
  const { token } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <div className="min-h-screen bg-page pb-14 font-sans text-ink md:pb-0">
      <NavBar />
      <Routes>
        <Route path="/" element={<FeedPage />} />
        <Route
          path="/holdings"
          element={
            <RequireAuth>
              <HoldingsPage />
            </RequireAuth>
          }
        />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
      </Routes>
      <BottomNav />
    </div>
  );
}
```

- [ ] **Step 4: Run the existing App tests to confirm they still pass**

Run: `npx vitest run src/App.test.tsx`
Expected: PASS (3 tests — routing assertions are unaffected by the wrapper className and the added `<BottomNav />`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/NavBar.tsx frontend/src/App.tsx
git commit -m "feat: collapse NavBar to logo-only on mobile, wire BottomNav into App"
```

---

### Task 10: Visual-consistency pass on Holdings/Login/Register

**Files:**
- Modify: `frontend/src/pages/HoldingsPage.tsx`
- Modify: `frontend/src/pages/LoginPage.tsx`
- Modify: `frontend/src/pages/RegisterPage.tsx`

**Interfaces:**
- Consumes: nothing new — these pages keep their existing child components (`HoldingsForm`, `HoldingsCsvUpload`, `HoldingsList`, `LoginForm`, `RegisterForm`) untouched.
- Produces: no new exports, headline scale only.

This is the "lighter visual-consistency pass" from the spec — not a restructure, just the same bumped-up bold headline scale used on `AlertCoverCard`'s hero headlines (`text-2xl` → `text-3xl`), so these pages read as part of the same redesigned system.

- [ ] **Step 1: Bump the `HoldingsPage` headline**

In `frontend/src/pages/HoldingsPage.tsx`, change:
```tsx
      <h1 className="mb-6 font-display text-2xl font-bold text-ink">My Holdings</h1>
```
to:
```tsx
      <h1 className="mb-6 font-display text-3xl font-bold text-ink">My Holdings</h1>
```

- [ ] **Step 2: Bump the `LoginPage` headline**

In `frontend/src/pages/LoginPage.tsx`, change:
```tsx
      <h1 className="mb-6 font-display text-2xl font-bold text-ink">Log in</h1>
```
to:
```tsx
      <h1 className="mb-6 font-display text-3xl font-bold text-ink">Log in</h1>
```

- [ ] **Step 3: Bump the `RegisterPage` headline**

In `frontend/src/pages/RegisterPage.tsx`, change:
```tsx
      <h1 className="mb-6 font-display text-2xl font-bold text-ink">Create account</h1>
```
to:
```tsx
      <h1 className="mb-6 font-display text-3xl font-bold text-ink">Create account</h1>
```

- [ ] **Step 4: Run the existing page tests to confirm they still pass**

Run: `npx vitest run src/App.test.tsx src/components/LoginForm.test.tsx src/components/RegisterForm.test.tsx`
Expected: PASS — these query by heading role/name, not by exact class, so the size bump doesn't affect them.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/HoldingsPage.tsx frontend/src/pages/LoginPage.tsx frontend/src/pages/RegisterPage.tsx
git commit -m "style: bump headline scale on Holdings/Login/Register for visual consistency"
```

---

### Task 11: Delete superseded components, final verification

**Files:**
- Delete: `frontend/src/components/AlertCard.tsx`
- Delete: `frontend/src/components/AlertCard.test.tsx`
- Delete: `frontend/src/components/FeedTabs.tsx`
- Delete: `frontend/src/components/FeedTabs.test.tsx`

**Interfaces:**
- Consumes: nothing (this task only removes files and verifies nothing else references them).
- Produces: nothing new.

- [ ] **Step 1: Verify nothing still imports the files being deleted**

Run (from `frontend/`):
```bash
grep -rn "from './AlertCard'" src/ ; grep -rn "from '../components/AlertCard'" src/
grep -rn "from './FeedTabs'" src/ ; grep -rn "from '../components/FeedTabs'" src/
```
Expected: no output from any of the four commands (only `Feed.tsx`/`FeedPage.tsx` used to import these, and both were rewritten in Task 8).

- [ ] **Step 2: Delete the files**

```bash
git rm frontend/src/components/AlertCard.tsx frontend/src/components/AlertCard.test.tsx
git rm frontend/src/components/FeedTabs.tsx frontend/src/components/FeedTabs.test.tsx
```

- [ ] **Step 3: Run the full frontend test suite**

Run: `npx vitest run`
Expected: PASS, all test files green (no leftover references to the deleted files).

- [ ] **Step 4: Run the TypeScript compiler**

Run: `npx tsc --noEmit`
Expected: no output (no type errors).

- [ ] **Step 5: Commit**

```bash
git commit -m "chore: delete AlertCard and FeedTabs, superseded by the Inshorts-style redesign"
```

---

## Self-Review Notes

- **Spec coverage:** mobile carousel (Task 6) + desktop grid (Task 7) + responsive toggle (Task 8's `Feed.tsx`) ✓; `AlertCoverCard`/`AlertCompanies`/`AlertDetail` component split ✓; `CategoryTabs` carrying `LiveStatus` + Custom-tab gear ✓; `BottomNav` ✓; "N new" live-queueing ✓; NavBar mobile collapse ✓; Holdings/Login/Register visual pass ✓; cleanup of superseded files ✓. Dark theme/serif font/no-new-dependencies constraints held throughout — no new Tailwind colors or npm packages introduced in any task.
- **Placeholder scan:** none — every step has complete, runnable code.
- **Type consistency:** `AlertCoverCard`'s `variant: 'carousel' | 'grid'` matches its usage in `MobileFeedCarousel`/`DesktopFeedGrid`; `CategoryTabs`' `FeedTab` type is the same union `Feed.tsx` uses for its own `tab` state; `AlertDetail`'s `{ open, onClose, children }` signature is identical across its three consumers (`BottomNav`'s account sheet, `Feed.tsx`'s alert-detail sheet, `Feed.tsx`'s settings sheet).
