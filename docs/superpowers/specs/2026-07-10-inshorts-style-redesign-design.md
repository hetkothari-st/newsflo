# NewsFlo — Inshorts-Style Feed Redesign

## Purpose

Replace the current scrollable list of alert cards with an Inshorts-inspired feed: full-screen, swipe-through cards on mobile and a bold card grid on desktop, so a user can scan market-moving news at a glance (image + headline + sentiment) without reading dense text first, and drill into company-level detail only when they want it.

## Scope

- Full redesign of the feed surface (mobile + web) and its supporting navigation.
- Lighter visual-consistency pass on Holdings / Login / Register (bumped type scale, card/input treatment) — not restructured into cards or swipe.
- Out of scope: backend/data-model changes (none needed — this consumes the existing `Alert`/`AlertCompany`/`image_url` API surface as-is), the swipe mechanic on desktop (grid + click instead, matching how inshorts.com itself differs from the Inshorts mobile app).

## Visual Direction

Keep NewsFlo's existing dark CRED-style base (near-black `page` background, `surface`/`hairline` card tokens, Georgia serif display headlines, swatch category colors, bullish/bearish greens/reds) — do not switch to Inshorts' light theme. Borrow Inshorts' *structure*: full-bleed hero imagery, bold oversized headlines, minimal-chrome full-screen cards, bottom tab navigation. The serif display font stays; headline scale/boldness goes up specifically on hero cards to read punchy at a glance, matching Inshorts' headline weight without swapping typefaces.

## Component Architecture

**New components:**

- `AlertCoverCard` (presentational) — full-bleed image (reuses existing `AlertCover` image + category-tinted-placeholder fallback logic) with a bottom gradient scrim (`bg-gradient-to-t from-page/95 via-page/40 to-transparent`, existing `page` token, no new palette), overlaid category swatch + timestamp (top), bold headline + sentiment pill (bottom). Takes a `variant: 'carousel' | 'grid'` prop that only changes sizing/aspect classes — one component, two contexts, not two components.
- `AlertCompanies` — extracted verbatim from the current `AlertCard`'s expanded-content logic (Predicted/Portfolio toggle, tier-grouped `CompanyChip` grid, empty-state copy). No behavior change, just relocated so both the mobile sheet and desktop modal reuse the same code instead of forking it.
- `AlertDetail` — one component, not two. Bottom sheet on mobile / centered modal on desktop via responsive classes (`fixed inset-x-0 bottom-0 rounded-t-lg md:inset-0 md:flex md:items-center md:justify-center md:bg-page/70`). Renders `AlertCompanies`. Backdrop click or Esc closes it; traps focus while open; slide/fade transition wrapped in `motion-safe:`/respects `motion-reduce:`.
- `MobileFeedCarousel` — CSS scroll-snap container (`snap-y snap-mandatory`, each card `snap-start h-dvh`) of `AlertCoverCard`s for the active category. No gesture library — native browser scroll-snap handles the swipe. Tapping a card sets `openAlertId` (owned by `Feed.tsx`, passed down).
- `DesktopFeedGrid` — responsive grid (`grid-cols-2 lg:grid-cols-3 gap-4`) of the same `AlertCoverCard`s, click sets the same `openAlertId`.
- `BottomNav` (mobile only) — fixed 3-item bar: Feed / Holdings / Account, active state from `useLocation()`.
- `CategoryTabs` — restyle of today's `FeedTabs` (bolder underline/weight), shared by both layouts. Carries the `LiveStatus` badge (right-aligned in the same row) and, on the Custom tab, a gear icon that opens the existing `WatchlistSettings` form inside the same `AlertDetail`-style sheet/modal shell (reused, not reinvented).

**Removed/replaced:** the current `AlertCard.tsx`'s inline click-to-expand-headline + inline Predicted/Portfolio buttons + inline tier-grouped grid — that entire interaction moves into `AlertCoverCard` (collapsed view) + `AlertDetail` (expanded view).

**Unchanged:** `CompanyChip`, `SentimentPill`, `CategorySwatch`, `AlertCover`'s image/fallback logic (consumed by `AlertCoverCard`), `WatchlistSettings`, `LiveStatus`'s connected/timer logic (only its layout position moves), `useAlertsSocket`, `feedFilters.ts`, all backend/API code.

## Layout Split (mobile vs desktop)

Both `MobileFeedCarousel` and `DesktopFeedGrid` mount from the same `Feed.tsx`-fetched `alerts` array — no duplicate fetching. Which one is visible is pure CSS breakpoint toggling (`block md:hidden` / `hidden md:block`), matching this codebase's existing responsive convention (no JS viewport-detection hook, avoids hydration mismatch risk). `AlertDetail` is a single instance at the `Feed` level reacting to `openAlertId`, regardless of which container is visible.

On mobile, the top `NavBar` collapses to a slim header (logo + account icon only) since `BottomNav` now owns Feed/Holdings/Account navigation. Desktop keeps today's full `NavBar` unchanged; no `BottomNav` on desktop.

## Data Flow / Live Updates

New alerts still arrive via the existing `useAlertsSocket` WebSocket push, merged into `Feed.tsx`'s `alerts` array exactly as today (`mergeAlerts`, unchanged). What changes is how the UI surfaces them: prepending a new full-height card above wherever the user currently is mid-scroll would shift their scroll-snap position (content inserted above the viewport pushes everything down). Instead, live arrivals are held back from the rendered list and surfaced as an "N new" pill next to `CategoryTabs`/`LiveStatus`; tapping it scrolls the carousel/grid to top and merges the queued alerts in. No jarring jumps while a user is mid-read.

## Edge Cases

- **Loading/error/empty states**: unchanged copy and logic, rendered centered inside whichever container is active.
- **No image**: `AlertCoverCard` falls back to the existing category-tinted placeholder (already built) instead of a broken image or blank card.
- **Custom tab, not configured**: same "choose categories or companies" empty-state copy, shown in place of the carousel/grid.
- **Reduced motion**: sheet/modal open-close and any scroll-snap-adjacent transitions respect `motion-reduce`.
- **Keyboard**: desktop grid cards are focusable and open `AlertDetail` on Enter/Space (matching the current `AlertCard`'s existing keyboard-expand pattern); `AlertDetail` traps focus and closes on Esc.

## Testing

This changes the interaction model completely, so most of `AlertCard.test.tsx` is rewritten (not patched) against the new components:

- `AlertCoverCard.test.tsx` — renders image/placeholder, headline, category, sentiment; click/Enter/Space calls its open handler.
- `AlertCompanies.test.tsx` — Predicted/Portfolio toggle, tier grouping, empty-state copy (this is largely today's `AlertCard` expanded-content assertions, relocated).
- `AlertDetail.test.tsx` — opens/closes on backdrop click and Esc, renders `AlertCompanies`/`WatchlistSettings` content, focus trap.
- `MobileFeedCarousel.test.tsx` / `DesktopFeedGrid.test.tsx` — render one card per alert, set `openAlertId` on interaction.
- `BottomNav.test.tsx` — active-link highlighting.
- `Feed.test.tsx` — updated for the "N new" queued-live-alert behavior instead of instant prepend.
- Existing `CompanyChip`, `SentimentPill`, `CategorySwatch`, `AlertCover`, `WatchlistSettings`, `useAlertsSocket`, `feedFilters` tests are unaffected (logic unchanged, only consumers move).

## Out of Scope

- Backend/API/data-model changes — none required.
- Switching to Inshorts' light theme.
- Swipe gesture on desktop (grid + click instead).
- Restructuring Holdings/Login/Register into cards (visual-consistency pass only).
- A settings/bookmarks/search bottom-nav item — `BottomNav` only carries sections that exist today (Feed/Holdings/Account).
