# Account Page — Design

Date: 2026-07-13

## Problem

NewsFlo (a NIFTY-market news/alerts app) has no dedicated account page. The
mobile bottom nav opens a sheet showing only the user's email and a Logout
button (`frontend/src/components/BottomNav.tsx`); desktop `NavBar.tsx` shows
email + Logout inline in the header. Watchlist settings live inside the Feed
page instead of any account surface. There's no way to change password, opt
out of email alerts, or delete an account.

## Goals

- One `/account` page consolidating profile, preferences, watchlist, holdings
  link, security, and account deletion.
- Add backend support for: fetching profile, changing password, toggling
  email alerts, deleting account.
- Reuse existing components (`LanguagePicker`, `ThemeToggle`,
  `WatchlistSettings`) rather than rebuilding them.

## Non-goals

- No change to holdings management UI itself (just a link to `/holdings`).
- No alembic/migration tooling introduced — see caveat below.
- No change to the JWT/session mechanism.

## Backend changes

`backend/app/models.py`:
- Add `email_alerts_enabled = Column(Boolean, nullable=False, default=True)`
  to `User`.

`backend/app/routers/auth.py` — new endpoints, all behind
`get_current_user`:
- `GET /api/auth/me` → `{id, email, created_at, email_alerts_enabled}`
- `PATCH /api/auth/me` — body `{email_alerts_enabled: bool}` → updates the
  toggle, returns updated profile
- `POST /api/auth/me/password` — body `{current_password, new_password}` →
  verifies `current_password` via `verify_password`, rejects with 401 if
  wrong, otherwise re-hashes and stores `new_password` (reuse the
  `AuthRequest` password length constraint: 1–72 chars)
- `DELETE /api/auth/me` — body `{password}` → verifies password, then in one
  transaction deletes the user's `Holding`, `UserWatchlistCategory`,
  `UserWatchlistCompany`, and `EmailNotification` rows, then the `User` row
  itself. Returns 204.

`backend/app/alerting/matcher.py`:
- In `match_alert_to_holdings`, join `Holding` to `User` and skip creating an
  `EmailNotification` when `user.email_alerts_enabled` is `False`. Disabled
  users never get a queued notification row (cleaner than filtering at send
  time in `sender.py`, which would create dead "skipped" rows).

**Caveat**: this repo has no migration tool (`db.py` comment: `create_all`
only creates missing tables, never adds columns to an existing table).
Existing local sqlite dev DBs will need to be recreated (delete the db file)
to pick up the new `email_alerts_enabled` column. This is a one-time local-dev
inconvenience, not a production concern mentioned in scope.

## Frontend changes

`frontend/src/lib/api.ts` — add:
- `getMe(token)`
- `updatePreferences(token, { email_alerts_enabled })`
- `changePassword(token, currentPassword, newPassword)`
- `deleteAccount(token, password)`

New `frontend/src/pages/AccountPage.tsx`, route `/account` wrapped in
`RequireAuth` (`App.tsx`). Sections, top to bottom:

1. **Profile** — email, "member since" (from `getMe`).
2. **Preferences** — `LanguagePicker`, `ThemeToggle`, and a new email-alerts
   on/off checkbox wired to `getMe`/`updatePreferences`.
3. **Watchlist** — `WatchlistSettings` component, rendered directly (not in
   an `AlertDetail` sheet, since the page itself is the modal-equivalent
   surface here). `Feed.tsx` already mounts the same component inside an
   `AlertDetail` sheet as the "Custom tab → gear icon" configuration flow
   (`components/Feed.tsx`, `settingsOpen` state) — that mount point is
   load-bearing UX and stays untouched. Account page adds a second, plain
   mount of the same component; this is component reuse, not duplicated
   logic.
4. **Holdings** — a card linking to `/holdings` (existing page, not
   duplicated here).
5. **Security** — change-password form (current + new password fields).
6. **Danger zone** — "Delete account" button opens a confirm dialog
   requiring password re-entry; on success calls `logout()` and redirects to
   `/`.
7. **Logout** button.

Nav wiring:
- `BottomNav.tsx`: the mobile account button becomes `Link to="/account"`
  (drop the `AlertDetail` sheet and its email+logout content entirely); the
  logged-out branch (`Link to="/login"`) is unchanged.
- `NavBar.tsx`: desktop's inline `email` + Logout button is replaced with a
  single `Link to="/account"`.

## i18n

New keys added to `CATALOG` in `frontend/src/lib/i18n.ts` under an
`account.*` namespace (profile labels, preferences labels, password-form
labels, delete-confirm copy, error/success messages), each with all 10
supported languages, following the existing catalog's structure and comment
conventions (native names, no auto-translation of the language picker
itself).

## Error handling

- Wrong current password on change-password → 401, shown inline under the
  form, form stays populated (except password fields, cleared).
- Wrong password on delete-confirm → 401, shown inline in the dialog, dialog
  stays open.
- Network/unexpected errors on any account-page action → inline message
  using the same pattern as `WatchlistSettings.tsx` (`message`/`isError`
  state), not a global toast.

## Testing

- Backend (pytest, alongside existing `backend/tests/`): new endpoint tests
  for `GET/PATCH /api/auth/me`, `POST /api/auth/me/password` (success +
  wrong-current-password), `DELETE /api/auth/me` (success + wrong-password +
  cascade verification), and a matcher test confirming a user with
  `email_alerts_enabled=False` gets no queued `EmailNotification`.
- Frontend (Vitest + RTL, matching existing `*.test.tsx` style): new
  `AccountPage.test.tsx` covering profile display, preference toggle,
  password-change success/failure, delete-account confirm flow, and that
  `WatchlistSettings` renders within the page. `Feed.test.tsx` and
  `WatchlistSettings.test.tsx` are unaffected (no changes to that mount
  point). `NavBar.test.tsx` and `BottomNav.test.tsx` updated: both now assert
  an `/account` link instead of inline email+logout / the logout-only sheet.
