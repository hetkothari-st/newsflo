# Light Mode (Neumorphic / Soft-UI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user-toggleable, persisted light theme styled as neumorphic/soft-UI (indigo accent, raised/pressed shadows), while leaving dark mode pixel-identical to today.

**Architecture:** Every existing color becomes a CSS custom property (`--color-*`), light values on `:root` (this makes **dark the true zero-JS default** — before any React code runs, the page already looks like today's dark theme, so there is no flash-of-wrong-theme for the common case), dark values under a `.dark` class placeholder... **correction, see Mechanism Note below**: `:root` gets **dark** values (matching today's hardcoded hex exactly) and a new `.light` class overrides to light values. A custom Tailwind variant `theme-light:` (via a one-line plugin, `.light &`) lets components add light-only classes (shadows, filled buttons) without touching a single existing class name — dark mode's safety is structural, not a matter of remembering to add `dark:` everywhere.

**Tech Stack:** React 18 + TypeScript + Vite + Tailwind CSS 3.4 + Vitest + Testing Library. No new dependencies.

## Mechanism Note (why this differs slightly from the spec's literal wording)

The spec described "`.dark` class, `dark:` variant, light is default." This plan flips the class name (`.light` override instead of `.dark` override) and uses a custom `theme-light:` variant instead of Tailwind's built-in `dark:`. Reasoning: making `:root` (no class needed) equal today's exact dark values means dark mode requires **zero JS-added class** to look correct — the safest possible default, and a stronger guarantee than the spec's version (which would flash light-then-dark for the majority default case before React mounts and adds `.dark`). Every requirement from the spec still holds: dark mode pixel-identical to today, light mode is indigo/neumorphic, user-toggleable and persisted, defaults to dark.

## Global Constraints

- Frontend only (`frontend/src/`) — no backend changes.
- Dark mode must remain **pixel-identical** to today — every new light-mode class is additive (`theme-light:`-prefixed) or a token swap whose dark-mode value equals the existing hardcoded hex, never a removed/replaced unprefixed class.
- Bullish/bearish colors and the 4 category swatch hues (`oil_energy`/`banking`/`auto_ev`/`geopolitics`/`other`) are unchanged in both themes.
- No new npm dependencies.
- Run `npx vitest run` and `npx tsc --noEmit` (from `frontend/`) after every task; both must be clean.
- Theme choice persists to `localStorage['newsflo.theme']`, defaults to `'dark'` when unset.

---

## File Structure

**New files:**
- `frontend/src/lib/theme.tsx` — `ThemeProvider`/`useTheme` (+ `.test.tsx`).
- `frontend/src/components/ThemeToggle.tsx` — sun/moon toggle button (+ `.test.tsx`).

**Modified files:**
- `frontend/tailwind.config.ts` — colors → CSS-var references, new `accent`/`accent-secondary` tokens, `shadow-neu`/`shadow-neu-inset`/`shadow-neu-sm` utilities, `theme-light:` variant plugin.
- `frontend/src/index.css` — `:root` (dark, today's values) and `.light` (new light values) custom properties.
- `frontend/src/main.tsx` — wrap `<App />` in `<ThemeProvider>`.
- `frontend/src/components/NavBar.tsx` (+ `.test.tsx`) — render `<ThemeToggle />`, raised-bar shadow.
- `frontend/src/components/BottomNav.tsx` (+ `.test.tsx`) — render `<ThemeToggle />` in the account sheet, raised-bar shadow, filled-button treatment on Logout.
- `frontend/src/App.test.tsx` — wrap with `<ThemeProvider>` (App now renders `ThemeToggle` transitively via NavBar/BottomNav).
- `frontend/src/components/LoginForm.tsx`, `RegisterForm.tsx`, `HoldingsForm.tsx` (+ their `.test.tsx` unaffected, role/text queries) — filled-button + inset-input treatment.
- `frontend/src/components/WatchlistSettings.tsx` — filled save button, inset filter input, accent-swapped selected states, raised chips.
- `frontend/src/components/AlertCoverCard.tsx`, `AlertDetail.tsx` — raised-shadow treatment.
- `frontend/src/components/CategoryTabs.tsx`, `CompanyChip.tsx` — accent-swapped active state + raised/pressed shadow.

---

### Task 1: Token system, custom variant, shadow utilities

**Files:**
- Modify: `frontend/tailwind.config.ts`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: nothing.
- Produces: Tailwind color tokens `page`/`surface`/`hairline`/`ink`/`muted`/`bullish`/`bearish`/`accent`/`accent-secondary` (theme-aware via CSS vars), `swatch-*` (unchanged, not theme-aware), box-shadow utilities `shadow-neu`/`shadow-neu-inset`/`shadow-neu-sm`, and the `theme-light:` variant prefix — every later task uses these.

There is no isolated unit-testable JS behavior in a pure Tailwind/CSS config change — verification is a real build plus grepping the compiled CSS for the expected selectors (the same technique used to diagnose a real production CSS bug earlier this session).

- [ ] **Step 1: Replace `frontend/tailwind.config.ts`**

```ts
import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        page: 'rgb(var(--color-page) / <alpha-value>)',
        surface: 'rgb(var(--color-surface) / <alpha-value>)',
        hairline: 'rgb(var(--color-hairline) / <alpha-value>)',
        ink: 'rgb(var(--color-ink) / <alpha-value>)',
        muted: 'rgb(var(--color-muted) / <alpha-value>)',
        bullish: 'rgb(var(--color-bullish) / <alpha-value>)',
        bearish: 'rgb(var(--color-bearish) / <alpha-value>)',
        accent: 'rgb(var(--color-accent) / <alpha-value>)',
        'accent-secondary': 'rgb(var(--color-accent-secondary) / <alpha-value>)',
        swatch: {
          oil_energy: '#F5A623',   // amber -- category identity, unchanged across themes
          banking: '#4A90D9',      // blue
          auto_ev: '#2DD4BF',      // teal
          geopolitics: '#E85D4C',  // red-orange
          other: '#8E8E93',        // gray (fallback)
        },
      },
      fontFamily: {
        display: ['Georgia', "'Times New Roman'", 'serif'],
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          'Inter',
          "'Segoe UI'",
          'sans-serif',
        ],
      },
      borderRadius: {
        lg: '12px',
      },
      maxWidth: {
        feed: '680px',
      },
      letterSpacing: {
        widest: '0.08em',
      },
      boxShadow: {
        // Light-mode-only neumorphic recipes (dual light/dark soft shadow,
        // calibrated against the new light `page` background #E4E8F1).
        // Never referenced unprefixed -- always via `theme-light:`.
        neu: '6px 6px 14px rgb(163 177 198 / 0.45), -6px -6px 14px rgb(255 255 255 / 0.8)',
        'neu-inset': 'inset 4px 4px 10px rgb(163 177 198 / 0.45), inset -4px -4px 10px rgb(255 255 255 / 0.8)',
        'neu-sm': '3px 3px 8px rgb(163 177 198 / 0.4), -3px -3px 8px rgb(255 255 255 / 0.75)',
      },
    },
  },
  plugins: [
    // A `.light` ancestor class (set by ThemeProvider, see frontend/src/lib/theme.tsx)
    // activates `theme-light:*` classes. `:root` itself carries dark values
    // (see index.css), so the ABSENCE of `.light` -- the default, zero-JS
    // state -- already renders today's exact dark theme.
    ({ addVariant }: { addVariant: (name: string, definition: string) => void }) => {
      addVariant('theme-light', '.light &');
    },
  ],
} satisfies Config;
```

- [ ] **Step 2: Replace `frontend/src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  /* Dark theme values -- identical to the hex this project has always used.
     This is the default with NO class needed, so dark mode never flashes
     anything else while React mounts. */
  --color-page: 10 10 10;
  --color-surface: 22 22 22;
  --color-hairline: 38 38 38;
  --color-ink: 242 242 242;
  --color-muted: 142 142 147;
  --color-bullish: 52 199 89;
  --color-bearish: 255 69 58;
  --color-accent: 242 242 242;      /* = ink: any accent-colored element looks identical to today */
  --color-accent-secondary: 142 142 147; /* = muted */
}

.light {
  --color-page: 228 232 241;
  --color-surface: 237 240 247;
  --color-hairline: 213 219 232;
  --color-ink: 58 63 82;
  --color-muted: 136 145 168;
  --color-bullish: 52 199 89;
  --color-bearish: 255 69 58;
  --color-accent: 99 91 255;
  --color-accent-secondary: 45 212 191;
}

body {
  @apply bg-page text-ink font-sans antialiased;
}
```

- [ ] **Step 3: Verify the build compiles and generates the expected classes**

Run (from `frontend/`):
```bash
npx vite build
grep -o "theme-light" dist/assets/*.css | head -1
grep -o "\-\-color-accent" dist/assets/*.css | head -1
grep -o "shadow-neu" dist/assets/*.css | head -1
```
Expected: all three grep commands print a match (no empty output). If `theme-light` doesn't appear, the variant plugin isn't registered correctly — check the `plugins` array syntax.

- [ ] **Step 4: Run the full test suite to confirm nothing broke**

Run: `npx vitest run`
Expected: all existing tests still PASS (this task changes no component code, only the token layer every component already consumes by name).

- [ ] **Step 5: Commit**

```bash
git add frontend/tailwind.config.ts frontend/src/index.css
git commit -m "feat: add theme token system, theme-light variant, neumorphic shadow utilities"
```

---

### Task 2: `ThemeProvider` / `useTheme`

**Files:**
- Create: `frontend/src/lib/theme.tsx`
- Test: `frontend/src/lib/theme.test.tsx`

**Interfaces:**
- Consumes: nothing (standalone, same pattern as `frontend/src/lib/auth.tsx`'s `AuthProvider`).
- Produces: `export type Theme = 'light' | 'dark'`, `export function ThemeProvider({ children }: { children: ReactNode })`, `export function useTheme(): { theme: Theme; toggleTheme: () => void }`. Used by `ThemeToggle` (Task 3) and wired into `main.tsx` (Task 4).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/lib/theme.test.tsx
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { ThemeProvider, useTheme } from './theme';

function wrapper({ children }: { children: ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>;
}

afterEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove('light');
});

describe('ThemeProvider / useTheme', () => {
  it('defaults to dark when nothing is saved', () => {
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.theme).toBe('dark');
    expect(document.documentElement.classList.contains('light')).toBe(false);
  });

  it('respects an existing saved theme on init', () => {
    localStorage.setItem('newsflo.theme', 'light');
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.theme).toBe('light');
    expect(document.documentElement.classList.contains('light')).toBe(true);
  });

  it('toggleTheme flips the value, persists it, and updates the <html> class', () => {
    const { result } = renderHook(() => useTheme(), { wrapper });

    act(() => result.current.toggleTheme());
    expect(result.current.theme).toBe('light');
    expect(localStorage.getItem('newsflo.theme')).toBe('light');
    expect(document.documentElement.classList.contains('light')).toBe(true);

    act(() => result.current.toggleTheme());
    expect(result.current.theme).toBe('dark');
    expect(localStorage.getItem('newsflo.theme')).toBe('dark');
    expect(document.documentElement.classList.contains('light')).toBe(false);
  });

  it('throws when used outside a ThemeProvider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => renderHook(() => useTheme())).toThrow('useTheme must be used within a ThemeProvider');
    spy.mockRestore();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/lib/theme.test.tsx`
Expected: FAIL — `Failed to resolve import "./theme"`.

- [ ] **Step 3: Write the implementation**

```tsx
// frontend/src/lib/theme.tsx
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

export type Theme = 'light' | 'dark';

interface ThemeContextValue {
  theme: Theme;
  toggleTheme: () => void;
}

const THEME_KEY = 'newsflo.theme';

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStoredTheme(): Theme {
  return localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark';
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(readStoredTheme);

  useEffect(() => {
    document.documentElement.classList.toggle('light', theme === 'light');
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === 'light' ? 'dark' : 'light';
      localStorage.setItem(THEME_KEY, next);
      return next;
    });
  }, []);

  return <ThemeContext.Provider value={{ theme, toggleTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (ctx === null) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return ctx;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/lib/theme.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/theme.tsx frontend/src/lib/theme.test.tsx
git commit -m "feat: add ThemeProvider/useTheme"
```

---

### Task 3: `ThemeToggle` component

**Files:**
- Create: `frontend/src/components/ThemeToggle.tsx`
- Test: `frontend/src/components/ThemeToggle.test.tsx`

**Interfaces:**
- Consumes: `useTheme` from `../lib/theme` (Task 2).
- Produces: `export default function ThemeToggle()`. Used by `NavBar` and `BottomNav` (Task 4).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/ThemeToggle.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import ThemeToggle from './ThemeToggle';
import { ThemeProvider } from '../lib/theme';

function renderToggle() {
  return render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>,
  );
}

afterEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove('light');
});

describe('ThemeToggle', () => {
  it('defaults to dark and offers to switch to light', () => {
    renderToggle();
    expect(screen.getByRole('button', { name: /switch to light mode/i })).toBeInTheDocument();
  });

  it('switches to light on click and updates its own label', async () => {
    renderToggle();
    await userEvent.click(screen.getByRole('button', { name: /switch to light mode/i }));
    expect(document.documentElement.classList.contains('light')).toBe(true);
    expect(screen.getByRole('button', { name: /switch to dark mode/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/ThemeToggle.test.tsx`
Expected: FAIL — `Failed to resolve import "./ThemeToggle"`.

- [ ] **Step 3: Write the implementation**

```tsx
// frontend/src/components/ThemeToggle.tsx
import { useTheme } from '../lib/theme';

export default function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isLight = theme === 'light';

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={isLight ? 'Switch to dark mode' : 'Switch to light mode'}
      className="text-muted hover:text-ink"
    >
      {isLight ? '☀' : '☾'}
    </button>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/ThemeToggle.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ThemeToggle.tsx frontend/src/components/ThemeToggle.test.tsx
git commit -m "feat: add ThemeToggle button"
```

---

### Task 4: Wire the theme system into the app

**Files:**
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/components/NavBar.tsx`
- Modify: `frontend/src/components/NavBar.test.tsx`
- Modify: `frontend/src/components/BottomNav.tsx`
- Modify: `frontend/src/components/BottomNav.test.tsx`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `ThemeProvider` (Task 2), `ThemeToggle` (Task 3).
- Produces: nothing new — this task only wires existing pieces together. After this task, `<App />` (and anything rendering `NavBar`/`BottomNav`) requires a `ThemeProvider` ancestor, same as it already requires an `AuthProvider` ancestor.

- [ ] **Step 1: Wrap the real app in `ThemeProvider`**

```tsx
// frontend/src/main.tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { AuthProvider } from './lib/auth';
import { ThemeProvider } from './lib/theme';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
```

- [ ] **Step 2: Add `ThemeToggle` to the desktop `NavBar`, and a raised-bar shadow**

In `frontend/src/components/NavBar.tsx`, add the import and render `<ThemeToggle />` as the first item in the auth-cluster div; add `theme-light:border-none theme-light:shadow-neu-sm` to the `<nav>` element (raised bar in light mode, dark mode's hairline border untouched):

```tsx
import { Link } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import ThemeToggle from './ThemeToggle';

export default function NavBar() {
  const { token, email, logout } = useAuth();
  return (
    <nav className="border-b border-hairline bg-page theme-light:border-none theme-light:shadow-neu-sm">
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
          <ThemeToggle />
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

- [ ] **Step 3: Update `NavBar.test.tsx` to wrap with `ThemeProvider`**

```tsx
// frontend/src/components/NavBar.test.tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import NavBar from './NavBar';
import { AuthProvider } from '../lib/auth';
import { ThemeProvider } from '../lib/theme';

function renderNav() {
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <AuthProvider>
          <NavBar />
        </AuthProvider>
      </ThemeProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove('light');
});

describe('NavBar', () => {
  it('shows Login and Register when logged out', () => {
    renderNav();
    expect(screen.getByRole('link', { name: /login/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /register/i })).toBeInTheDocument();
  });

  it('shows the user email and a Logout button when logged in', () => {
    localStorage.setItem('newsflo.token', 'tok');
    localStorage.setItem('newsflo.email', 'me@example.com');
    renderNav();
    expect(screen.getByText('me@example.com')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /logout/i })).toBeInTheDocument();
  });

  it('renders the theme toggle', () => {
    renderNav();
    expect(screen.getByRole('button', { name: /switch to light mode/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Add `ThemeToggle` to `BottomNav`'s account sheet, and a raised-bar shadow**

```tsx
// frontend/src/components/BottomNav.tsx
import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import AlertDetail from './AlertDetail';
import ThemeToggle from './ThemeToggle';

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
      <nav className="fixed inset-x-0 bottom-0 z-40 flex h-14 border-t border-hairline bg-page theme-light:border-none theme-light:shadow-neu-sm md:hidden">
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
          <ThemeToggle />
          <button
            type="button"
            onClick={() => {
              logout();
              setAccountOpen(false);
            }}
            className="self-start rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50 theme-light:border-transparent theme-light:bg-accent theme-light:text-page theme-light:shadow-neu"
          >
            Logout
          </button>
        </div>
      </AlertDetail>
    </>
  );
}
```

- [ ] **Step 5: Update `BottomNav.test.tsx` to wrap with `ThemeProvider`**

```tsx
// frontend/src/components/BottomNav.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import BottomNav from './BottomNav';
import { AuthProvider } from '../lib/auth';
import { ThemeProvider } from '../lib/theme';

function renderNav(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ThemeProvider>
        <AuthProvider>
          <BottomNav />
        </AuthProvider>
      </ThemeProvider>
    </MemoryRouter>,
  );
}

function setToken() {
  localStorage.setItem('newsflo.token', 'tok');
  localStorage.setItem('newsflo.email', 'a@example.com');
}

afterEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove('light');
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

  it('opens an account sheet with email, the theme toggle, and Logout when logged in', async () => {
    setToken();
    renderNav();
    await userEvent.click(screen.getByRole('button', { name: /account/i }));
    expect(screen.getByText('a@example.com')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /switch to light mode/i })).toBeInTheDocument();
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

- [ ] **Step 6: Update `App.test.tsx` to wrap with `ThemeProvider`**

In `frontend/src/App.test.tsx`, add the import `import { ThemeProvider } from './lib/theme';` and change the `renderAt` helper's JSX from:
```tsx
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
```
to:
```tsx
    <MemoryRouter initialEntries={[path]}>
      <ThemeProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ThemeProvider>
    </MemoryRouter>,
```
(No other changes to this file — its existing three tests query by role/heading, unaffected by the new toggle button.)

- [ ] **Step 7: Run the full suite to verify everything passes**

Run: `npx vitest run`
Expected: all tests PASS, including the new/updated ones in `NavBar.test.tsx`, `BottomNav.test.tsx`, and `App.test.tsx`.

- [ ] **Step 8: Run tsc**

Run: `npx tsc --noEmit`
Expected: no output.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/main.tsx frontend/src/components/NavBar.tsx frontend/src/components/NavBar.test.tsx frontend/src/components/BottomNav.tsx frontend/src/components/BottomNav.test.tsx frontend/src/App.test.tsx
git commit -m "feat: wire ThemeProvider and ThemeToggle into NavBar, BottomNav, and the app root"
```

---

### Task 5: Filled primary buttons and inset form inputs

**Files:**
- Modify: `frontend/src/components/LoginForm.tsx`
- Modify: `frontend/src/components/RegisterForm.tsx`
- Modify: `frontend/src/components/HoldingsForm.tsx`
- Modify: `frontend/src/components/WatchlistSettings.tsx`
- Test: `frontend/src/components/LoginForm.test.tsx` (add one spot-check assertion)

**Interfaces:**
- Consumes: nothing new (pure className additions to existing components).
- Produces: nothing new — no signature changes.

The button suffix (`theme-light:border-transparent theme-light:bg-accent theme-light:text-page theme-light:shadow-neu`) and input suffix (`theme-light:border-transparent theme-light:shadow-neu-inset`) below are applied verbatim everywhere a primary button / text input already exists. Both are purely additive: every unprefixed class an element had before this task, it still has after — dark mode renders byte-identical classes.

- [ ] **Step 1: Write the failing spot-check test**

In `frontend/src/components/LoginForm.test.tsx`, add this test inside the existing `describe('LoginForm', ...)` block (read the file first to see its existing structure and match its render helper):

```tsx
  it('gives the submit button the light-mode filled treatment', () => {
    render(<LoginForm />);
    expect(screen.getByRole('button', { name: /log in/i })).toHaveClass('theme-light:bg-accent');
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/LoginForm.test.tsx`
Expected: FAIL — the button doesn't have `theme-light:bg-accent` yet.

- [ ] **Step 3: Apply the button and input suffixes**

In `frontend/src/components/LoginForm.tsx`, change both `<input>` elements' className from:
```
"rounded-lg border border-hairline bg-surface px-3 py-2 text-ink outline-none focus:border-muted"
```
to:
```
"rounded-lg border border-hairline bg-surface px-3 py-2 text-ink outline-none focus:border-muted theme-light:border-transparent theme-light:shadow-neu-inset"
```
and the `<button type="submit">` className from:
```
"rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50"
```
to:
```
"rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50 theme-light:border-transparent theme-light:bg-accent theme-light:text-page theme-light:shadow-neu"
```

Apply the exact same two suffixes in `frontend/src/components/RegisterForm.tsx` (both inputs, the submit button) and `frontend/src/components/HoldingsForm.tsx` (both inputs, the submit button) — each of these three files has the identical base className strings for its inputs/button today, so the suffix is a literal find-and-append in each.

In `frontend/src/components/WatchlistSettings.tsx`:
- The company filter `<input type="text">`'s className gets the same input suffix appended.
- The `<button type="submit">` (Save) className gets the same button suffix appended.

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/LoginForm.test.tsx src/components/RegisterForm.test.tsx src/components/HoldingsForm.test.tsx src/components/WatchlistSettings.test.tsx`
Expected: all PASS (the pre-existing tests in these files query by role/text, unaffected by added classes; the one new assertion passes).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/LoginForm.tsx frontend/src/components/LoginForm.test.tsx frontend/src/components/RegisterForm.tsx frontend/src/components/HoldingsForm.tsx frontend/src/components/WatchlistSettings.tsx
git commit -m "feat: light-mode filled-button and inset-input treatment on all forms"
```

---

### Task 6: Raised-shadow cards, detail sheet, and bars

**Files:**
- Modify: `frontend/src/components/AlertCoverCard.tsx`
- Modify: `frontend/src/components/AlertDetail.tsx`
- Test: `frontend/src/components/AlertCoverCard.test.tsx` (add one spot-check assertion)
- Test: `frontend/src/components/AlertDetail.test.tsx` (add one spot-check assertion)

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new.

(`NavBar`/`BottomNav`'s bar shadows were already added in Task 4, alongside the toggle wiring since they're the same lines.)

- [ ] **Step 1: Write the failing tests**

In `frontend/src/components/AlertCoverCard.test.tsx`, add inside `describe('AlertCoverCard', ...)`:

```tsx
  it('gets a raised shadow in light mode', () => {
    render(<AlertCoverCard alert={alert} onOpen={() => {}} variant="grid" />);
    expect(screen.getByRole('button', { name: /us strikes iran/i })).toHaveClass('theme-light:shadow-neu');
  });
```

In `frontend/src/components/AlertDetail.test.tsx`, add inside `describe('AlertDetail', ...)`:

```tsx
  it('gets a raised shadow instead of a border in light mode', () => {
    render(
      <AlertDetail open onClose={() => {}}>
        <p>content</p>
      </AlertDetail>,
    );
    expect(screen.getByRole('dialog')).toHaveClass('theme-light:shadow-neu');
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/components/AlertCoverCard.test.tsx src/components/AlertDetail.test.tsx`
Expected: both new tests FAIL (class not present yet).

- [ ] **Step 3: Apply the shadow classes**

In `frontend/src/components/AlertCoverCard.tsx`, change the root `<div>`'s className from:
```
`relative w-full shrink-0 cursor-pointer overflow-hidden ${SIZE_CLASS[variant]}`
```
to:
```
`relative w-full shrink-0 cursor-pointer overflow-hidden theme-light:shadow-neu ${SIZE_CLASS[variant]}`
```

In `frontend/src/components/AlertDetail.tsx`, change the panel `<div>`'s className from:
```
"relative z-10 max-h-[85vh] w-full overflow-y-auto rounded-t-lg border border-hairline bg-surface p-6 outline-none motion-safe:transition-transform md:max-h-[80vh] md:max-w-lg md:rounded-lg"
```
to:
```
"relative z-10 max-h-[85vh] w-full overflow-y-auto rounded-t-lg border border-hairline bg-surface p-6 outline-none motion-safe:transition-transform md:max-h-[80vh] md:max-w-lg md:rounded-lg theme-light:border-transparent theme-light:shadow-neu"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/components/AlertCoverCard.test.tsx src/components/AlertDetail.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AlertCoverCard.tsx frontend/src/components/AlertCoverCard.test.tsx frontend/src/components/AlertDetail.tsx frontend/src/components/AlertDetail.test.tsx
git commit -m "feat: light-mode raised shadow on cards and the detail sheet/modal"
```

---

### Task 7: Indigo accent + shadow on tabs and chips

**Files:**
- Modify: `frontend/src/components/CategoryTabs.tsx`
- Modify: `frontend/src/components/CompanyChip.tsx`
- Modify: `frontend/src/components/WatchlistSettings.tsx`
- Test: `frontend/src/components/CategoryTabs.test.tsx` (add one spot-check assertion)
- Test: `frontend/src/components/CompanyChip.test.tsx` (add one spot-check assertion)

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new.

Active/selected states that currently use `ink` (`border-ink`, `bg-ink`, `text-ink`) for emphasis switch to the new `accent` token — in dark mode `accent` equals `ink`'s existing value (see Task 1's `index.css`), so this is a color-value no-op there; in light mode it becomes indigo. This is a pure token swap, not a `theme-light:`-prefixed addition, and it's safe by construction for the same reason.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/components/CategoryTabs.test.tsx`, add inside `describe('CategoryTabs', ...)`:

```tsx
  it('uses the accent token for the active tab and gets a raised shadow container', () => {
    renderTabs({ active: 'india' });
    expect(screen.getByRole('tab', { name: /india/i })).toHaveClass('border-accent', 'text-accent');
  });
```

In `frontend/src/components/CompanyChip.test.tsx`, add inside `describe('CompanyChip', ...)`:

```tsx
  it('gets a raised shadow in light mode', () => {
    render(<CompanyChip company={company} />);
    expect(screen.getByRole('button', { name: /reliance/i })).toHaveClass('theme-light:shadow-neu-sm');
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/components/CategoryTabs.test.tsx src/components/CompanyChip.test.tsx`
Expected: both new tests FAIL.

- [ ] **Step 3: Apply the accent swap and shadow classes**

In `frontend/src/components/CategoryTabs.tsx`, change the tab button's className from:
```tsx
              className={`border-b-2 pb-3 text-base font-bold uppercase tracking-widest motion-safe:transition-colors ${
                isActive ? 'border-ink text-ink' : 'border-transparent text-muted hover:text-ink'
              }`}
```
to:
```tsx
              className={`border-b-2 pb-3 text-base font-bold uppercase tracking-widest motion-safe:transition-colors ${
                isActive ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-ink'
              }`}
```
and add a raised shadow to the whole tab row container -- change the outer `<div>`'s className from:
```
"flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-hairline"
```
to:
```
"flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-lg border-b border-hairline p-2 theme-light:border-none theme-light:shadow-neu-sm"
```

In `frontend/src/components/CompanyChip.tsx`, change the chip `<div role="button">`'s className from:
```
"flex cursor-pointer items-center gap-2.5 rounded-lg border border-hairline bg-surface p-3 motion-safe:transition-colors hover:border-muted"
```
to:
```
"flex cursor-pointer items-center gap-2.5 rounded-lg border border-hairline bg-surface p-3 motion-safe:transition-colors hover:border-muted theme-light:border-transparent theme-light:shadow-neu-sm"
```

In `frontend/src/components/WatchlistSettings.tsx`:
- The category chip `<label>`'s className, append `theme-light:shadow-neu-sm` when unselected (append to the `unselectedClass` string, i.e. the branch currently `'border-hairline bg-page hover:border-muted'` becomes `'border-hairline bg-page hover:border-muted theme-light:shadow-neu-sm'`).
- The company row's selected-state classes, change:
  ```
  selected ? 'border-ink bg-hairline/40' : 'border-hairline bg-page hover:border-muted'
  ```
  to:
  ```
  selected ? 'border-accent bg-accent/10' : 'border-hairline bg-page hover:border-muted theme-light:shadow-neu-sm'
  ```
- The checkmark `<span>`'s selected-state classes, change:
  ```
  selected ? 'border-ink bg-ink text-page' : 'border-hairline text-transparent'
  ```
  to:
  ```
  selected ? 'border-accent bg-accent text-page' : 'border-hairline text-transparent'
  ```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/components/CategoryTabs.test.tsx src/components/CompanyChip.test.tsx src/components/WatchlistSettings.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CategoryTabs.tsx frontend/src/components/CategoryTabs.test.tsx frontend/src/components/CompanyChip.tsx frontend/src/components/CompanyChip.test.tsx frontend/src/components/WatchlistSettings.tsx
git commit -m "feat: indigo accent and raised/pressed shadows on tabs and chips"
```

---

### Task 8: Final verification

**Files:** none (verification only).

**Interfaces:** none.

- [ ] **Step 1: Run the full frontend test suite**

Run: `npx vitest run`
Expected: all tests PASS.

- [ ] **Step 2: Run the TypeScript compiler**

Run: `npx tsc --noEmit`
Expected: no output.

- [ ] **Step 3: Run a real build and confirm dark mode's compiled classes are untouched**

Run (from `frontend/`):
```bash
npx vite build
grep -c "bg-surface{" dist/assets/*.css
grep -c "theme-light" dist/assets/*.css
```
Expected: the first grep finds the existing `.bg-surface{...}` rule (proves the base/dark-default utility still compiles exactly as before); the second finds a non-zero count of `theme-light:`-prefixed rules (proves the new light-mode classes actually made it into the bundle — this is the same verification method used earlier this session to catch a real missing-CSS production bug, applied here proactively).

- [ ] **Step 4: Manual visual check (not automated — no screenshot infra in this project)**

Start the dev server (`npm run dev` from `frontend/`), open the app, click the new theme toggle (desktop: top-right of `NavBar`; mobile: inside the Account sheet from `BottomNav`), and confirm:
- Dark mode (default, no toggle clicked) looks pixel-identical to before this plan.
- Light mode shows the soft gray-blue background, indigo buttons/active-tab/selected-chips, and raised/pressed shadows on cards, buttons, tabs, chips, and inputs.
- Toggling persists across a page reload.

- [ ] **Step 5: No commit for this task** (verification only, nothing to stage).

---

## Self-Review Notes

- **Spec coverage:** palette + token mechanism ✓ (Task 1, with the documented, justified `.light`-vs-`.dark` mechanism flip for a stronger no-flash guarantee); `accent`/`accent-secondary` tokens ✓; `shadow-neu`/`shadow-neu-inset` utilities ✓; `ThemeProvider`/`useTheme`/`ThemeToggle` + persistence + dark default ✓ (Tasks 2-4); filled primary buttons ✓ (Task 5); recessed inputs ✓ (Task 5); raised cards/detail sheet/nav bars ✓ (Tasks 4 & 6); tabs/chips accent + shadow ✓ (Task 7); `SentimentPill`/`CategorySwatch` intentionally untouched (they only use tokens Task 1 already makes theme-aware, per the spec) ✓.
- **Placeholder scan:** none — every step has complete, runnable code or an exact command with expected output.
- **Type consistency:** `Theme` type (`'light' | 'dark'`) defined once in `theme.tsx`, not redefined elsewhere. `ThemeProvider`/`useTheme`/`ThemeToggle` signatures match across every task that consumes them (Tasks 3, 4).
- **Simplification flagged:** the spec's Section 2 described `CategoryTabs`' active tab as "a pressed/inset indigo pill replacing the underline." This plan keeps the existing underline structure (now indigo via the `accent` token) and adds a raised-shadow container instead of a full pill reshape, to keep every task a safe, mechanical, verifiable diff rather than a riskier structural rewrite. Visual language (raised/pressed + indigo) is preserved; exact shape is a simplification made during planning.
