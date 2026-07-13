# NewsFlo — Light Mode (Neumorphic / Soft-UI)

## Purpose

Add a light theme, styled as neumorphic/soft-UI per the user's reference images: soft gray-blue background, indigo/violet primary accent, teal secondary accent, raised-shadow cards and buttons, pressed/inset selected states. Dark mode (today's CRED-style near-black look) stays exactly as-is — this is an additive theme, not a redesign of dark mode.

## Scope

- A `light`/`dark` theme toggle, user-switchable, persisted, defaulting to dark for first-time visitors.
- Every existing surface recolors correctly in light mode via a token-based mechanism (no per-component work needed for pure color).
- A subset of components get additional neumorphic shadow/shape treatment (buttons, cards, tabs, chips, inputs, nav bars) — this part **does** require per-component changes, since "flat bordered surface" vs "raised shadow surface" isn't a pure color swap.
- Bullish/bearish colors and the 4 category swatch hues are unchanged across both themes — they're semantic identifiers, not decoration.
- Out of scope: dark mode redesign, decorative marketing-page elements from the reference images (concentric circles, etc. — don't fit a dense data app), SSR/flash-of-wrong-theme handling (pure client SPA, not applicable).

## Palette

New light-mode token values (dark mode's existing hex values are unchanged):

| Token | Dark (unchanged) | Light (new) |
|---|---|---|
| `page` | `#0A0A0A` | `#E4E8F1` |
| `surface` | `#161616` | `#EDF0F7` |
| `ink` | `#F2F2F2` | `#3A3F52` |
| `muted` | `#8E8E93` | `#8891A8` |
| `hairline` | `#262626` | `#D5DBE8` |
| `bullish` | `#34C759` | `#34C759` (unchanged) |
| `bearish` | `#FF453A` | `#FF453A` (unchanged) |
| `swatch-*` (4 category hues) | unchanged | unchanged |

New tokens (both themes need a value; dark mode's value equals its existing `ink`, so dark mode's appearance is provably unaffected):

| Token | Dark | Light |
|---|---|---|
| `accent` (indigo) | `#F2F2F2` (= `ink`, dark unaffected) | `#635BFF` |
| `accent-secondary` (teal) | `#8E8E93` (= `muted`, dark unaffected) | `#2DD4BF` |

## Theming Mechanism

Convert every color in `tailwind.config.ts` from a hardcoded hex to a CSS custom property reference (`page: 'rgb(var(--color-page) / <alpha-value>)'`, etc.). Define light values on `:root` and dark values under a `.dark` class in `index.css`. Because every existing component already uses named tokens (never raw hex), this recolors the entire app for free — zero component changes for anything that's a pure color swap.

`accent`/`accent-secondary` are net-new tokens. Any component that currently uses `border-ink`/`bg-ink`/`text-ink` specifically for an **active/selected/interactive state** (not body text) switches to `border-accent`/`bg-accent`/`text-accent` instead — this is the "indigo everywhere" requirement. Plain text usage of `ink` is untouched.

Two things are not pure color and need real `dark:`-variant work per component:

- **Neumorphic shadows.** New Tailwind `boxShadow` utilities: `shadow-neu` (raised, dual light/dark soft shadow calibrated for the light background) and `shadow-neu-inset` (pressed/recessed, for selected chips/tabs and form inputs). These are light-mode-only recipes — dark mode gets `dark:shadow-none` alongside them to keep its flat hairline-border look exactly as today.
- **Filled primary buttons.** No such style exists today (every button is currently outline: `border-hairline bg-surface text-ink`). Light mode's default (unprefixed) classes become a filled indigo pill (`bg-accent text-page shadow-neu`); `dark:` variants restore today's exact outline classes.

## Theme State & Toggle

- `frontend/src/lib/theme.tsx`: `ThemeProvider` (same pattern as the existing `AuthProvider`) — `useState<Theme>` initialized from `localStorage['newsflo.theme']`, defaulting to `'dark'` when unset. A `useEffect` toggles the `.dark` class on `document.documentElement` whenever `theme` changes. `toggleTheme()` flips the value and persists it. `useTheme()` hook throws outside the provider, matching `useAuth()`'s existing contract.
- New `ThemeToggle` component: a small sun/moon icon button calling `toggleTheme()`. Rendered in `NavBar` (desktop, next to the account cluster) and inside `BottomNav`'s account sheet (mobile) — both are places a user already looks for account-adjacent controls.

## Component Treatment

Every interactive surface reads as **raised** at rest and **pressed/inset** when active or selected — the one consistent visual thread across all of it, not per-component improvisation:

- **Primary buttons** (Save, Log in, Register, Add holding, custom-settings gear): new filled-indigo-pill style, `shadow-neu` at rest, `shadow-neu-inset` on `:active`. Secondary/cancel actions keep an outline look on the neumorphic surface (soft inset border, no fill).
- **`AlertCoverCard`**: outer edge gains `shadow-neu` (a soft raised card floating off the page). No change to internal layout/content.
- **`CategoryTabs`**: the tab track becomes a raised pill; the active tab gets a pressed/inset indigo pill behind it, replacing today's underline. Inactive tabs stay flush/flat.
- **Chips** (`CompanyChip`, `WatchlistSettings` category/company pickers): unselected = raised pill with soft shadow; selected = pressed/inset with an indigo border — same interaction language as tabs.
- **Form inputs** (Login/Register/Holdings/WatchlistSettings filter): recessed "well" look via `shadow-neu-inset`, no visible border.
- **`NavBar`/`BottomNav`**: raised shadow separating the bar from the page, replacing the hairline border.
- **`AlertDetail`** sheet/modal: raised shadow instead of a hairline border.
- **`SentimentPill`, `CategorySwatch`**: unchanged shape — these are semantic (bullish/bearish, category identity), not decorative. They only recolor via the token swap, no shadow treatment.

## Testing

- `theme.tsx`: `ThemeProvider`/`useTheme` unit tests — defaults to dark when nothing saved, respects an existing saved value on init, `toggleTheme()` flips the value and persists it, applies/removes the `.dark` class on `document.documentElement`.
- `ThemeToggle.test.tsx`: renders, clicking calls `toggleTheme()` (via a real `ThemeProvider`, asserting the class change) or is wired through the context correctly.
- Spot-check tests (not an exhaustive per-component sweep) on a representative primary button, `AlertCoverCard`, and `CategoryTabs` confirming the new `shadow-neu`/`dark:` classes are present.
- No visual/screenshot testing infrastructure exists in this project — verification of the actual neumorphic look is manual (dev server + browser), same as this session's earlier redesign work.

## Out of Scope

- Dark mode visual changes — every new `accent`/`shadow-neu` usage on an existing component ships with a `dark:` override that reproduces today's exact classes, and the palette table above shows dark's new-token values equal existing tokens for this reason.
- Decorative elements from the reference images (concentric circles, illustration graphics) — don't fit a financial alert feed.
- SSR / flash-of-unstyled-theme — not applicable, pure client-rendered SPA.
- System-preference (`prefers-color-scheme`) auto-detection — explicitly decided against; default is always dark for new visitors, user toggle is the only way to reach light.
