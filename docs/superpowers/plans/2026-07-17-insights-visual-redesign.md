# Insights Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the textual per-company reasoning block in the affected-companies feed with a compact, scannable, editorial-styled card, move full reasoning to a dedicated detail page, and add real Brandfetch company logos.

**Architecture:** Backend gains a shared `_logo_url` helper (moved out of `companies.py`), a `logo_url` field on the alerts endpoint's per-company payload, and a relaxed `GET /api/companies/{id}/prices` that now serves `GLOBAL`-market companies too. Frontend gains a small set of pure-function helpers (relative time, confidence/horizon/impact display mappings), three new leaf components (`CompanyLogo`, `InsightSparkline`, `InsightGauges`) composed into a new `InsightCard` that replaces `CompanyChip`'s collapsed-row-plus-inline-accordion pattern, and a new `AlertCompanyAnalysisPage` that ports `ReasoningPanel`'s content to its own route with the same editorial visual language.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript + Tailwind + react-router-dom (frontend), pytest (backend tests), vitest + Testing Library (frontend tests). Two new Google Fonts (`Newsreader`, `IBM Plex Mono`) loaded via CSS `@import`.

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-07-17-insights-visual-redesign-design.md` — every task below implements a specific section of it; consult it for the full rationale.
- Dark-theme colors (default, no class needed): `page #0A0A0A`, `surface #161616`, `hairline #262626`, `ink #F2F2F2`, `muted #8E8E93`, `bullish #34C759`, `bearish #FF453A`. Use the existing Tailwind tokens (`bg-page`, `text-ink`, `border-hairline`, `text-muted`, `text-bullish`, `text-bearish`) — never hardcode these hex values in component code.
- Light-theme colors (`.light` class): `page #E4E8F1`, `surface #EDF0F7`, `hairline #D5DBE8`, `ink #3A3F52`, `muted #8891A8`, `accent #635BFF`, `accent-secondary #2DD4BF`. Same rule: use Tailwind tokens (`text-accent`, etc.), never hardcode hex.
- New fonts apply ONLY to the new insight-card/detail-page surfaces via new Tailwind font-family tokens `editorial` (Newsreader) and `data` (IBM Plex Mono) — do NOT change the existing `display`/`sans` tokens or any other component's fonts.
- No card shadows, no `rounded-lg` card containers, no colored left-borders, no emoji icons anywhere in the new components — hairline (`border-hairline`, 1px) rules only, per the design spec's explicit rejection of that look.
- New static-copy strings (gauge labels, horizon/impact values, "See more/less", "Read full analysis", relative-time strings) follow the established precedent already used for `reasoning.whyThisCall`, `reasoning.confidenceBreakdown`, `reasoning.confidenceLow/Moderate/High/VeryHigh`, and `reasoning.factsHeading` in `frontend/src/lib/i18n.ts`: the same English string repeated for all 10 language codes (verified existing precedent — these are technical/reasoning-domain terms this codebase deliberately does not translate).
- Every new/modified backend function that touches `Company`/`AlertCompany` follows the codebase's "never raise, degrade to None" contract already used throughout `app/reasoning/financial_context.py` and `app/routers/companies.py`.

---

## File Structure

**Backend:**
- Create `backend/app/companies/branding.py` — `_logo_url` moved here (renamed `logo_url`, no longer private since two routers import it).
- Modify `backend/app/routers/companies.py` — import `logo_url` from the new module instead of defining it; relax `_get_indian_company_or_404` usage at the `/prices` endpoint.
- Modify `backend/app/routers/alerts.py` — add `logo_url` to `_serialize_alert`'s per-company dict.
- Modify `backend/tests/test_companies_api.py` — update the two existing logo-url tests to patch the new module path.
- Modify `backend/tests/test_api.py` — add a `logo_url`-on-alerts test; add prices-endpoint GLOBAL-market tests (new test, adjacent to existing prices tests in `test_companies_api.py`).

**Frontend:**
- Create `frontend/src/lib/relativeTime.ts` + `frontend/src/lib/relativeTime.test.ts`.
- Create `frontend/src/lib/insightMappings.ts` + `frontend/src/lib/insightMappings.test.ts`.
- Modify `frontend/src/lib/i18n.ts` — add new `insights.*` translation keys.
- Modify `frontend/src/lib/api.ts` — add `logo_url?: string | null` to `AlertCompany`.
- Modify `frontend/src/index.css` — add the Google Fonts `@import`.
- Modify `frontend/tailwind.config.ts` — add `editorial`/`data` font-family tokens.
- Create `frontend/src/components/CompanyLogo.tsx` + `frontend/src/components/CompanyLogo.test.tsx` (replaces `CompanyAvatar.tsx`).
- Create `frontend/src/components/InsightSparkline.tsx` + `frontend/src/components/InsightSparkline.test.tsx`.
- Create `frontend/src/components/InsightGauges.tsx` + `frontend/src/components/InsightGauges.test.tsx`.
- Create `frontend/src/components/InsightCard.tsx` + `frontend/src/components/InsightCard.test.tsx` (replaces `CompanyChip.tsx`).
- Modify `frontend/src/components/AlertCompanies.tsx` — single-column `InsightCard` feed instead of a 2-col `CompanyChip` grid.
- Modify `frontend/src/components/AlertCompanies.test.tsx` — update for the new rendering.
- Create `frontend/src/pages/AlertCompanyAnalysisPage.tsx` + `frontend/src/pages/AlertCompanyAnalysisPage.test.tsx` (ports `ReasoningPanel`'s content).
- Modify `frontend/src/App.tsx` — add the new route.
- Modify `frontend/src/App.test.tsx` — add a route-smoke-test entry if the existing test enumerates routes (check during Task 13).
- Delete `frontend/src/components/CompanyChip.tsx`, `frontend/src/components/CompanyChip.test.tsx`, `frontend/src/components/ReasoningPanel.tsx`, `frontend/src/components/ReasoningPanel.test.tsx`, `frontend/src/components/CompanyAvatar.tsx`, `frontend/src/components/CompanyAvatar.test.tsx` (final cleanup task, once nothing references them).

---

## Task 1: Shared `logo_url` helper

**Files:**
- Create: `backend/app/companies/branding.py`
- Modify: `backend/app/routers/companies.py`
- Modify: `backend/tests/test_companies_api.py`

**Interfaces:**
- Produces: `logo_url(company: Company) -> str | None` in `app.companies.branding`, used by Task 2.

- [ ] **Step 1: Write the failing test (module path change)**

In `backend/tests/test_companies_api.py`, update the two logo-url tests to patch the new location. Replace:

```python
def test_list_companies_includes_isin_and_logo_url(db_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "brandfetch_client_id", "")
```

with (unchanged body otherwise — `settings` is still the right patch target since the new module reads the same setting):

```python
def test_list_companies_includes_isin_and_logo_url(db_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "brandfetch_client_id", "")
```

(No change needed to this test's body — it patches `app.config.settings`, not the function location, so it will pass once Task 1's Step 3 wires the import correctly. This step is a no-op confirmation, not an edit — skip directly to Step 2's new test.)

Add one new test to `backend/tests/test_companies_api.py` (after `test_list_companies_logo_url_uses_isin_when_client_id_set`):

```python
def test_branding_logo_url_importable_from_shared_module(db_session, monkeypatch):
    from app.companies.branding import logo_url
    from app.config import settings
    from app.models import Company

    monkeypatch.setattr(settings, "brandfetch_client_id", "test-client-id")
    company = Company(ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None)

    assert logo_url(company) == "https://cdn.brandfetch.io/ticker/AAPL?c=test-client-id"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companies_api.py::test_branding_logo_url_importable_from_shared_module -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.branding'`

- [ ] **Step 3: Create the shared module and update the import site**

Create `backend/app/companies/branding.py`:

```python
from app.config import settings
from app.models import Company


def logo_url(company: Company) -> str | None:
    if not settings.brandfetch_client_id:
        return None
    if company.isin:
        return f"https://cdn.brandfetch.io/isin/{company.isin}?c={settings.brandfetch_client_id}"
    return f"https://cdn.brandfetch.io/ticker/{company.ticker}?c={settings.brandfetch_client_id}"
```

In `backend/app/routers/companies.py`, remove the local `_logo_url` definition (lines 23-28) and its `from app.config import settings` import (no longer used directly in this file — confirm nothing else in the file references `settings` before removing the import; if something else does, keep the import and only remove the function), then:

```python
from app.companies.branding import logo_url as _logo_url
```

Add this import alongside the existing `from app.companies...` imports at the top of the file, keeping the local name `_logo_url` so every existing call site (`_logo_url(c)` at line 52, `_logo_url(company)` at line 95) needs no further edits.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_companies_api.py -v`
Expected: All tests PASS, including the new one and the two pre-existing logo-url tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/branding.py backend/app/routers/companies.py backend/tests/test_companies_api.py
git commit -m "refactor: move logo_url lookup to a shared companies.branding module"
```

---

## Task 2: `logo_url` on the alerts endpoint

**Files:**
- Modify: `backend/app/routers/alerts.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `logo_url(company: Company) -> str | None` from Task 1's `app.companies.branding`.
- Produces: every company dict `_serialize_alert` returns now has a `"logo_url"` key.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api.py` (place it near `test_list_alerts_includes_company_sector`, following that test's exact seeding pattern):

```python
def test_list_alerts_includes_company_logo_url(db_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "brandfetch_client_id", "test-client-id")

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(
        source="test", url="https://example.com/logo", title="Logo test headline",
        status="ANALYZED", category="oil_energy",
    )
    db_session.add(article)
    db_session.commit()

    company = Company(
        ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0, isin="INE002A01018",
    )
    db_session.add(company)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    assert response.json()[0]["companies"][0]["logo_url"] == (
        "https://cdn.brandfetch.io/isin/INE002A01018?c=test-client-id"
    )

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_api.py::test_list_alerts_includes_company_logo_url -v`
Expected: FAIL with `KeyError: 'logo_url'`

- [ ] **Step 3: Add the field**

In `backend/app/routers/alerts.py`, add the import:

```python
from app.companies.branding import logo_url
```

In `_serialize_alert`'s per-company dict (the `companies.append({...})` block, lines 36-62), add one line — placed next to the other `ac.company.*` reads for locality:

```python
            "company_id": ac.company_id, "ticker": ac.company.ticker, "name": ac.company.name,
            "index_tier": ac.company.index_tier, "sector": ac.company.sector,
            "sub_sector": ac.company.sub_sector, "logo_url": logo_url(ac.company),
```

(This replaces the first two lines of the existing block shown above — everything else in the dict is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_api.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/alerts.py backend/tests/test_api.py
git commit -m "feat: expose logo_url on alert companies"
```

---

## Task 3: Relax the prices endpoint to serve `GLOBAL` companies

**Files:**
- Modify: `backend/app/routers/companies.py`
- Modify: `backend/tests/test_companies_api.py`

**Interfaces:**
- Produces: `GET /api/companies/{id}/prices` now returns 200 for a `GLOBAL`-market company (previously 404).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_companies_api.py` (after `test_get_company_prices_invalid_period_returns_400`):

```python
def test_get_company_prices_works_for_global_company(db_session, monkeypatch):
    from app.routers import companies as companies_router

    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None)
    db_session.add(company)
    db_session.commit()
    monkeypatch.setattr(
        companies_router, "fetch_price_series",
        lambda ticker, period: [{"date": "2026-01-01", "close": 200.0}],
    )
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/prices?period=1mo").json()

    assert body == {"period": "1mo", "points": [{"date": "2026-01-01", "close": 200.0}], "available": True}
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_companies_api.py::test_get_company_prices_works_for_global_company -v`
Expected: FAIL — `assert 404 == 200` (the response has no `.json()` body matching, since the endpoint currently 404s for non-IN companies).

- [ ] **Step 3: Relax the endpoint**

In `backend/app/routers/companies.py`, add a new lookup function next to `_get_indian_company_or_404`:

```python
def _get_company_or_404(db: Session, company_id: int) -> Company:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(404, "Company not found")
    return company
```

In `get_company_prices` (the `/{company_id}/prices` route), change:

```python
    company = _get_indian_company_or_404(db, company_id)
```

to:

```python
    company = _get_company_or_404(db, company_id)
```

Leave every other `_get_indian_company_or_404` call site in the file unchanged (profile, history, live-price all stay IN-only per the design spec — only `/prices` is relaxed).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_companies_api.py -v`
Expected: All tests PASS, including the existing `test_get_company_prices_invalid_period_returns_400` and the new GLOBAL-market test.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/companies.py backend/tests/test_companies_api.py
git commit -m "feat: serve price series for GLOBAL-market companies, not just IN"
```

---

## Task 4: `relativeTime` utility

**Files:**
- Create: `frontend/src/lib/relativeTime.ts`
- Create: `frontend/src/lib/relativeTime.test.ts`
- Modify: `frontend/src/lib/i18n.ts`

**Interfaces:**
- Produces: `formatRelativeTime(iso: string, now: Date, lang: Language): string`, used by Task 11 (`InsightCard`).

- [ ] **Step 1: Add the i18n keys**

In `frontend/src/lib/i18n.ts`, add these four entries to `CATALOG` (insert them right before the closing `} as const;` at line 786, matching the existing "English repeated for every language" precedent used by `reasoning.whyThisCall`/`reasoning.confidenceBreakdown`/`reasoning.factsHeading` for reasoning-domain technical terms):

```ts
  'insights.justNow': {
    en: 'just now', hi: 'just now', mr: 'just now', gu: 'just now', ml: 'just now', te: 'just now',
    ta: 'just now', kn: 'just now', pa: 'just now', bn: 'just now',
  },
  'insights.minutesAgo': {
    en: '{n}m ago', hi: '{n}m ago', mr: '{n}m ago', gu: '{n}m ago', ml: '{n}m ago', te: '{n}m ago',
    ta: '{n}m ago', kn: '{n}m ago', pa: '{n}m ago', bn: '{n}m ago',
  },
  'insights.hoursAgo': {
    en: '{n}h ago', hi: '{n}h ago', mr: '{n}h ago', gu: '{n}h ago', ml: '{n}h ago', te: '{n}h ago',
    ta: '{n}h ago', kn: '{n}h ago', pa: '{n}h ago', bn: '{n}h ago',
  },
  'insights.daysAgo': {
    en: '{n}d ago', hi: '{n}d ago', mr: '{n}d ago', gu: '{n}d ago', ml: '{n}d ago', te: '{n}d ago',
    ta: '{n}d ago', kn: '{n}d ago', pa: '{n}d ago', bn: '{n}d ago',
  },
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/lib/relativeTime.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { formatRelativeTime } from './relativeTime';

const NOW = new Date('2026-07-17T12:00:00.000Z');

describe('formatRelativeTime', () => {
  it('shows "just now" under 60 seconds', () => {
    expect(formatRelativeTime('2026-07-17T11:59:30.000Z', NOW, 'en')).toBe('just now');
  });

  it('shows minutes at the 60-second boundary', () => {
    expect(formatRelativeTime('2026-07-17T11:59:00.000Z', NOW, 'en')).toBe('1m ago');
  });

  it('shows minutes just under an hour', () => {
    expect(formatRelativeTime('2026-07-17T11:01:00.000Z', NOW, 'en')).toBe('59m ago');
  });

  it('shows hours at the 60-minute boundary', () => {
    expect(formatRelativeTime('2026-07-17T11:00:00.000Z', NOW, 'en')).toBe('1h ago');
  });

  it('shows hours just under a day', () => {
    expect(formatRelativeTime('2026-07-16T13:00:00.000Z', NOW, 'en')).toBe('23h ago');
  });

  it('shows days at the 24-hour boundary', () => {
    expect(formatRelativeTime('2026-07-16T12:00:00.000Z', NOW, 'en')).toBe('1d ago');
  });

  it('shows days just under a week', () => {
    expect(formatRelativeTime('2026-07-11T13:00:00.000Z', NOW, 'en')).toBe('6d ago');
  });

  it('falls back to an absolute date at 7 days and beyond', () => {
    const result = formatRelativeTime('2026-07-10T12:00:00.000Z', NOW, 'en');
    expect(result).not.toMatch(/ago$/);
    expect(result).toContain('Jul');
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/relativeTime.test.ts`
Expected: FAIL with `Cannot find module './relativeTime'`

- [ ] **Step 4: Write the implementation**

Create `frontend/src/lib/relativeTime.ts`:

```ts
import type { Language } from './i18n';
import { translate } from './i18n';

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const WEEK_MS = 7 * DAY_MS;

// `now` is a required param (not `new Date()` internally) so this stays a
// pure, deterministically testable function -- callers pass the real
// current time in production and a fixed Date in tests.
export function formatRelativeTime(iso: string, now: Date, lang: Language): string {
  const then = new Date(iso);
  const diffMs = now.getTime() - then.getTime();

  if (diffMs < MINUTE_MS) return translate(lang, 'insights.justNow');
  if (diffMs < HOUR_MS) return translate(lang, 'insights.minutesAgo', { n: Math.floor(diffMs / MINUTE_MS) });
  if (diffMs < DAY_MS) return translate(lang, 'insights.hoursAgo', { n: Math.floor(diffMs / HOUR_MS) });
  if (diffMs < WEEK_MS) return translate(lang, 'insights.daysAgo', { n: Math.floor(diffMs / DAY_MS) });

  return then.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/relativeTime.test.ts`
Expected: All 8 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/relativeTime.ts frontend/src/lib/relativeTime.test.ts frontend/src/lib/i18n.ts
git commit -m "feat: add relative-time formatter for the insight card feed"
```

---

## Task 5: `insightMappings` utility (confidence/horizon/impact display values)

**Files:**
- Create: `frontend/src/lib/insightMappings.ts`
- Create: `frontend/src/lib/insightMappings.test.ts`
- Modify: `frontend/src/lib/i18n.ts`

**Interfaces:**
- Produces: `confidenceDotCount(score: number): number`, `horizonGlyph(timeHorizon: string): string`, `horizonLabel(timeHorizon: string, lang: Language): string`, `impactLabel(level: string | undefined, lang: Language): string` — all used by Task 8 (`InsightGauges`).

- [ ] **Step 1: Add the i18n keys**

In `frontend/src/lib/i18n.ts`, add these entries to `CATALOG` (same "English repeated for every language" precedent as Task 4):

```ts
  'insights.horizonImmediate': {
    en: 'Immediate', hi: 'Immediate', mr: 'Immediate', gu: 'Immediate', ml: 'Immediate', te: 'Immediate',
    ta: 'Immediate', kn: 'Immediate', pa: 'Immediate', bn: 'Immediate',
  },
  'insights.horizonShort': {
    en: 'Short', hi: 'Short', mr: 'Short', gu: 'Short', ml: 'Short', te: 'Short',
    ta: 'Short', kn: 'Short', pa: 'Short', bn: 'Short',
  },
  'insights.horizonMedium': {
    en: 'Medium', hi: 'Medium', mr: 'Medium', gu: 'Medium', ml: 'Medium', te: 'Medium',
    ta: 'Medium', kn: 'Medium', pa: 'Medium', bn: 'Medium',
  },
  'insights.horizonLong': {
    en: 'Long', hi: 'Long', mr: 'Long', gu: 'Long', ml: 'Long', te: 'Long',
    ta: 'Long', kn: 'Long', pa: 'Long', bn: 'Long',
  },
  'insights.impactDirect': {
    en: 'Direct', hi: 'Direct', mr: 'Direct', gu: 'Direct', ml: 'Direct', te: 'Direct',
    ta: 'Direct', kn: 'Direct', pa: 'Direct', bn: 'Direct',
  },
  'insights.impactIndirect': {
    en: 'Indirect', hi: 'Indirect', mr: 'Indirect', gu: 'Indirect', ml: 'Indirect', te: 'Indirect',
    ta: 'Indirect', kn: 'Indirect', pa: 'Indirect', bn: 'Indirect',
  },
  'insights.impactIndirectL2': {
    en: 'Indirect · 2nd-order', hi: 'Indirect · 2nd-order', mr: 'Indirect · 2nd-order',
    gu: 'Indirect · 2nd-order', ml: 'Indirect · 2nd-order', te: 'Indirect · 2nd-order',
    ta: 'Indirect · 2nd-order', kn: 'Indirect · 2nd-order', pa: 'Indirect · 2nd-order',
    bn: 'Indirect · 2nd-order',
  },
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/lib/insightMappings.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { confidenceDotCount, horizonGlyph, horizonLabel, impactLabel } from './insightMappings';

describe('confidenceDotCount', () => {
  it('is 0 at score 0', () => {
    expect(confidenceDotCount(0)).toBe(0);
  });

  it('rounds to the nearest dot', () => {
    expect(confidenceDotCount(20)).toBe(1);
    expect(confidenceDotCount(21)).toBe(1);
    expect(confidenceDotCount(84)).toBe(4);
  });

  it('is 5 at score 100', () => {
    expect(confidenceDotCount(100)).toBe(5);
  });
});

describe('horizonGlyph', () => {
  it('maps each horizon to a distinct glyph', () => {
    expect(horizonGlyph('Immediate')).toBe('●');
    expect(horizonGlyph('Short-Term')).toBe('◔');
    expect(horizonGlyph('Medium-Term')).toBe('◑');
    expect(horizonGlyph('Long-Term')).toBe('◯');
  });

  it('falls back to the medium glyph for an unrecognized value', () => {
    expect(horizonGlyph('unknown')).toBe('◑');
  });
});

describe('horizonLabel', () => {
  it('strips "-Term" from each horizon value', () => {
    expect(horizonLabel('Short-Term', 'en')).toBe('Short');
    expect(horizonLabel('Medium-Term', 'en')).toBe('Medium');
    expect(horizonLabel('Long-Term', 'en')).toBe('Long');
    expect(horizonLabel('Immediate', 'en')).toBe('Immediate');
  });
});

describe('impactLabel', () => {
  it('labels direct impact', () => {
    expect(impactLabel('direct', 'en')).toBe('Direct');
  });

  it('labels first-order indirect impact', () => {
    expect(impactLabel('indirect_l1', 'en')).toBe('Indirect');
  });

  it('labels second-order indirect impact distinctly', () => {
    expect(impactLabel('indirect_l2', 'en')).toBe('Indirect · 2nd-order');
  });

  it('defaults to direct when the level is undefined (legacy alerts)', () => {
    expect(impactLabel(undefined, 'en')).toBe('Direct');
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/insightMappings.test.ts`
Expected: FAIL with `Cannot find module './insightMappings'`

- [ ] **Step 4: Write the implementation**

Create `frontend/src/lib/insightMappings.ts`:

```ts
import type { Language } from './i18n';
import { translate } from './i18n';

export function confidenceDotCount(score: number): number {
  return Math.max(0, Math.min(5, Math.round(score / 20)));
}

const HORIZON_GLYPH: Record<string, string> = {
  Immediate: '●',
  'Short-Term': '◔',
  'Medium-Term': '◑',
  'Long-Term': '◯',
};

export function horizonGlyph(timeHorizon: string): string {
  return HORIZON_GLYPH[timeHorizon] ?? '◑';
}

const HORIZON_LABEL_KEY = {
  Immediate: 'insights.horizonImmediate',
  'Short-Term': 'insights.horizonShort',
  'Medium-Term': 'insights.horizonMedium',
  'Long-Term': 'insights.horizonLong',
} as const;

export function horizonLabel(timeHorizon: string, lang: Language): string {
  const key = HORIZON_LABEL_KEY[timeHorizon as keyof typeof HORIZON_LABEL_KEY];
  return key ? translate(lang, key) : timeHorizon;
}

export function impactLabel(level: string | undefined, lang: Language): string {
  if (level === 'indirect_l1') return translate(lang, 'insights.impactIndirect');
  if (level === 'indirect_l2') return translate(lang, 'insights.impactIndirectL2');
  return translate(lang, 'insights.impactDirect');
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/insightMappings.test.ts`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/insightMappings.ts frontend/src/lib/insightMappings.test.ts frontend/src/lib/i18n.ts
git commit -m "feat: add confidence/horizon/impact display mapping helpers"
```

---

## Task 6: Editorial fonts and Tailwind tokens

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/tailwind.config.ts`

**Interfaces:**
- Produces: Tailwind utility classes `font-editorial` (Newsreader) and `font-data` (IBM Plex Mono), usable by every task from Task 7 onward.

- [ ] **Step 1: Add the font import**

In `frontend/src/index.css`, add this as the very first line of the file (CSS requires `@import` to precede every other rule, including `@tailwind`):

```css
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&family=IBM+Plex+Mono:wght@400;500&display=swap');
```

The file's existing first line (`@tailwind base;`) and everything after it stays unchanged, just pushed down by this new line.

- [ ] **Step 2: Add the Tailwind tokens**

In `frontend/tailwind.config.ts`, extend the existing `fontFamily` block (do not remove `display`/`sans`):

```ts
      fontFamily: {
        display: ['Georgia', "'Times New Roman'", 'serif'],
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          'Inter',
          "'Segoe UI'",
          'sans-serif',
        ],
        editorial: ["'Newsreader'", 'Georgia', 'serif'],
        data: ["'IBM Plex Mono'", 'monospace'],
      },
```

- [ ] **Step 3: Verify the build picks up the change**

Run: `cd frontend && npm run build`
Expected: Build succeeds (0 errors) — this step has no unit test of its own since it's pure config; the real verification is every later task's components rendering with the new fonts, checked visually per the design spec's "Explicitly out of scope" note about a real visual check before calling this done.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/index.css frontend/tailwind.config.ts
git commit -m "feat: load Newsreader/IBM Plex Mono fonts for the insights redesign"
```

---

## Task 7: `logo_url` on the `AlertCompany` TypeScript type

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Produces: `AlertCompany.logo_url?: string | null`, consumed by Task 8 (`CompanyLogo`) via Task 11 (`InsightCard`).

- [ ] **Step 1: Add the field**

In `frontend/src/lib/api.ts`, in the `AlertCompany` interface, add `logo_url` next to the other company-identity fields (after `sub_sector`, before `direction`):

```ts
  sub_sector?: string | null;
  // Real company logo from Brandfetch (see backend app.companies.branding),
  // null when no BRANDFETCH_CLIENT_ID is configured or Brandfetch has no
  // match for this company -- CompanyLogo degrades to a monogram either way.
  logo_url?: string | null;
  direction: string; // bullish | bearish
```

No new test needed for this step alone (it's a type-only change with no runtime behavior) — Task 8's `CompanyLogo` tests and Task 11's `InsightCard` tests exercise it.

- [ ] **Step 2: Run the frontend typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 errors (this is an additive optional field, cannot break existing code).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add logo_url to the AlertCompany type"
```

---

## Task 8: `CompanyLogo` component (replaces `CompanyAvatar`)

**Files:**
- Create: `frontend/src/components/CompanyLogo.tsx`
- Create: `frontend/src/components/CompanyLogo.test.tsx`

**Interfaces:**
- Produces: `<CompanyLogo logoUrl={string | null | undefined} ticker={string} size={'md' | 'lg'} />`, consumed by Task 11 (`InsightCard`) and Task 13 (`AlertCompanyAnalysisPage`).
- Note: this is a NEW component alongside the still-present `CompanyAvatar.tsx` (deleted only in the final Task 14, once nothing references it) — do not modify `CompanyAvatar.tsx` in this task.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/CompanyLogo.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CompanyLogo from './CompanyLogo';

// The logo is intentionally decorative (alt="") -- the company name is
// already rendered as adjacent text in every consumer, so a screen reader
// would announce it twice with a descriptive alt. An empty-alt <img> has
// implicit role="presentation", not "img", so it must be queried by tag
// (container.querySelector) rather than screen.getByRole('img').
describe('CompanyLogo', () => {
  it('renders an img with the given logo url', () => {
    const { container } = render(<CompanyLogo logoUrl="https://cdn.brandfetch.io/ticker/AAPL?c=x" ticker="AAPL" />);
    const img = container.querySelector('img');
    expect(img).toHaveAttribute('src', 'https://cdn.brandfetch.io/ticker/AAPL?c=x');
  });

  it('shows a monogram fallback when logoUrl is null', () => {
    const { container } = render(<CompanyLogo logoUrl={null} ticker="RELIANCE.NS" />);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('RE')).toBeInTheDocument();
  });

  it('shows a monogram fallback when logoUrl is undefined', () => {
    render(<CompanyLogo logoUrl={undefined} ticker="AAPL" />);
    expect(screen.getByText('AA')).toBeInTheDocument();
  });

  it('swaps to the monogram fallback on image load error', () => {
    const { container } = render(<CompanyLogo logoUrl="https://cdn.brandfetch.io/ticker/BAD?c=x" ticker="BAD" />);
    const img = container.querySelector('img')!;
    img.dispatchEvent(new Event('error'));
    expect(screen.getByText('BA')).toBeInTheDocument();
  });

  it('uses the ticker prefix before any dot suffix for the monogram', () => {
    render(<CompanyLogo logoUrl={null} ticker="RELIANCE.NS" />);
    expect(screen.getByText('RE')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/CompanyLogo.test.tsx`
Expected: FAIL with `Cannot find module './CompanyLogo'`

- [ ] **Step 3: Write the implementation**

Create `frontend/src/components/CompanyLogo.tsx`:

```tsx
import { useState } from 'react';

function initials(ticker: string): string {
  const base = ticker.split('.')[0];
  return base.slice(0, 2).toUpperCase();
}

const SIZE_CLASS = {
  md: 'h-11 w-11 text-sm',
  lg: 'h-16 w-16 text-lg',
} as const;

export default function CompanyLogo({
  logoUrl,
  ticker,
  size = 'md',
}: {
  logoUrl?: string | null;
  ticker: string;
  size?: 'md' | 'lg';
}) {
  const [failed, setFailed] = useState(false);
  const showFallback = !logoUrl || failed;

  return (
    <span
      className={`flex shrink-0 items-center justify-center overflow-hidden border border-hairline bg-page ${SIZE_CLASS[size]}`}
    >
      {showFallback ? (
        <span className="font-data text-muted" aria-hidden="true">
          {initials(ticker)}
        </span>
      ) : (
        <img
          src={logoUrl}
          alt=""
          className="h-full w-full object-contain"
          onError={() => setFailed(true)}
        />
      )}
    </span>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/CompanyLogo.test.tsx`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CompanyLogo.tsx frontend/src/components/CompanyLogo.test.tsx
git commit -m "feat: add CompanyLogo component with real-image and monogram fallback"
```

---

## Task 9: `InsightSparkline` component

**Files:**
- Create: `frontend/src/components/InsightSparkline.tsx`
- Create: `frontend/src/components/InsightSparkline.test.tsx`

**Interfaces:**
- Consumes: `PricePoint[]` from `frontend/src/lib/api.ts` (already defined: `{ date: string; close: number }`).
- Produces: `<InsightSparkline points={PricePoint[]} direction={'bullish' | 'bearish' | string} />`, consumed by Task 11 (`InsightCard`).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/InsightSparkline.test.tsx`:

```tsx
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import InsightSparkline from './InsightSparkline';
import type { PricePoint } from '../lib/api';

const POINTS: PricePoint[] = [
  { date: '2026-06-17', close: 100 },
  { date: '2026-06-24', close: 105 },
  { date: '2026-07-01', close: 98 },
  { date: '2026-07-17', close: 112 },
];

describe('InsightSparkline', () => {
  it('renders an svg with one polyline point per price point', () => {
    const { container } = render(<InsightSparkline points={POINTS} direction="bullish" />);
    const polyline = container.querySelector('polyline');
    expect(polyline).not.toBeNull();
    const drawnPoints = polyline!.getAttribute('points')!.trim().split(/\s+/);
    expect(drawnPoints).toHaveLength(POINTS.length);
  });

  it('colors the line bullish-green for a bullish direction', () => {
    const { container } = render(<InsightSparkline points={POINTS} direction="bullish" />);
    expect(container.querySelector('polyline')).toHaveClass('stroke-bullish');
  });

  it('colors the line bearish-red for a bearish direction', () => {
    const { container } = render(<InsightSparkline points={POINTS} direction="bearish" />);
    expect(container.querySelector('polyline')).toHaveClass('stroke-bearish');
  });

  it('renders nothing when there are fewer than 2 points', () => {
    const { container } = render(<InsightSparkline points={[POINTS[0]]} direction="bullish" />);
    expect(container.querySelector('svg')).toBeNull();
  });

  it('renders nothing for an empty points array', () => {
    const { container } = render(<InsightSparkline points={[]} direction="bullish" />);
    expect(container.querySelector('svg')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/InsightSparkline.test.tsx`
Expected: FAIL with `Cannot find module './InsightSparkline'`

- [ ] **Step 3: Write the implementation**

Create `frontend/src/components/InsightSparkline.tsx`:

```tsx
import type { PricePoint } from '../lib/api';

const WIDTH = 480;
const HEIGHT = 40;
const PAD = 4;

export default function InsightSparkline({
  points,
  direction,
}: {
  points: PricePoint[];
  direction: string;
}) {
  if (points.length < 2) return null;

  const closes = points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;

  const coords = points.map((p, i) => {
    const x = (i / (points.length - 1)) * WIDTH;
    const y = HEIGHT - PAD - ((p.close - min) / range) * (HEIGHT - PAD * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const strokeClass = direction === 'bearish' ? 'stroke-bearish' : 'stroke-bullish';
  const firstY = coords[0].split(',')[1];

  return (
    <svg width="100%" height={HEIGHT} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none">
      <line
        x1={0}
        y1={firstY}
        x2={WIDTH}
        y2={firstY}
        className="stroke-hairline"
        strokeWidth={1}
        strokeDasharray="1,3"
      />
      <polyline points={coords.join(' ')} fill="none" className={strokeClass} strokeWidth={1.75} />
    </svg>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/InsightSparkline.test.tsx`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/InsightSparkline.tsx frontend/src/components/InsightSparkline.test.tsx
git commit -m "feat: add InsightSparkline component"
```

---

## Task 10: `InsightGauges` component

**Files:**
- Create: `frontend/src/components/InsightGauges.tsx`
- Create: `frontend/src/components/InsightGauges.test.tsx`

**Interfaces:**
- Consumes: `confidenceDotCount`, `horizonGlyph`, `horizonLabel`, `impactLabel` from Task 5's `frontend/src/lib/insightMappings.ts`.
- Produces: `<InsightGauges confidenceScore={number} timeHorizon={string} impactLevel={string | undefined} />`, consumed by Task 11 (`InsightCard`).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/InsightGauges.test.tsx`:

```tsx
import { render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import InsightGauges from './InsightGauges';
import { LanguageProvider } from '../lib/language';

function render(ui: ReactElement) {
  return rtlRender(<LanguageProvider>{ui}</LanguageProvider>);
}

describe('InsightGauges', () => {
  it('shows the confidence percentage and filled dot count', () => {
    render(<InsightGauges confidenceScore={84} timeHorizon="Short-Term" impactLevel="direct" />);
    expect(screen.getByText('84%')).toBeInTheDocument();
    expect(screen.getAllByTestId('confidence-dot-filled')).toHaveLength(4);
  });

  it('shows the horizon label and glyph', () => {
    render(<InsightGauges confidenceScore={50} timeHorizon="Medium-Term" impactLevel="direct" />);
    expect(screen.getByText('Medium')).toBeInTheDocument();
    expect(screen.getByText('◑')).toBeInTheDocument();
  });

  it('shows the impact label', () => {
    render(<InsightGauges confidenceScore={50} timeHorizon="Short-Term" impactLevel="indirect_l1" />);
    expect(screen.getByText('Indirect')).toBeInTheDocument();
  });

  it('defaults impact to Direct when impactLevel is undefined', () => {
    render(<InsightGauges confidenceScore={50} timeHorizon="Short-Term" impactLevel={undefined} />);
    expect(screen.getByText('Direct')).toBeInTheDocument();
  });

  it('labels all three columns', () => {
    render(<InsightGauges confidenceScore={50} timeHorizon="Short-Term" impactLevel="direct" />);
    expect(screen.getByText('Confidence')).toBeInTheDocument();
    expect(screen.getByText('Horizon')).toBeInTheDocument();
    expect(screen.getByText('Impact')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/InsightGauges.test.tsx`
Expected: FAIL with `Cannot find module './InsightGauges'`

- [ ] **Step 3: Write the implementation**

Create `frontend/src/components/InsightGauges.tsx`. "Confidence"/"Horizon"/"Impact" are the column headers themselves, not translated dynamic content requiring a lookup — plain literals, matching the design spec's mono labels and consistent with how `reasoning.*` keys are already English-literal for this same category of term:

```tsx
import { useLanguage } from '../lib/language';
import { confidenceDotCount, horizonGlyph, horizonLabel, impactLabel } from '../lib/insightMappings';

export default function InsightGauges({
  confidenceScore,
  timeHorizon,
  impactLevel,
}: {
  confidenceScore: number;
  timeHorizon: string;
  impactLevel: string | undefined;
}) {
  const { language } = useLanguage();
  const filledDots = confidenceDotCount(confidenceScore);

  return (
    <div className="grid grid-cols-3 py-1.5">
      <div className="grid grid-rows-[auto_auto_20px] items-center justify-items-center gap-2">
        <span className="font-data text-[10.5px] uppercase tracking-widest text-bullish">Confidence</span>
        <span className="font-data text-[15px] font-semibold text-ink">{confidenceScore}%</span>
        <div className="flex items-center justify-center gap-1">
          {Array.from({ length: 5 }, (_, i) => (
            <span
              key={i}
              data-testid={i < filledDots ? 'confidence-dot-filled' : 'confidence-dot-empty'}
              className={`h-1.5 w-1.5 rounded-full ${i < filledDots ? 'bg-bullish' : 'bg-hairline'}`}
            />
          ))}
        </div>
      </div>
      <div className="grid grid-rows-[auto_auto_20px] items-center justify-items-center gap-2 border-l border-hairline">
        <span className="font-data text-[10.5px] uppercase tracking-widest text-muted">Horizon</span>
        <span className="font-data text-[15px] font-semibold text-ink">{horizonLabel(timeHorizon, language)}</span>
        <span className="flex items-center text-lg leading-none text-ink" aria-hidden="true">
          {horizonGlyph(timeHorizon)}
        </span>
      </div>
      <div className="grid grid-rows-[auto_auto_20px] items-center justify-items-center gap-2 border-l border-hairline">
        <span className="font-data text-[10.5px] uppercase tracking-widest text-muted">Impact</span>
        <span className="font-data text-[15px] font-semibold text-ink">{impactLabel(impactLevel, language)}</span>
        <span />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/InsightGauges.test.tsx`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/InsightGauges.tsx frontend/src/components/InsightGauges.test.tsx
git commit -m "feat: add InsightGauges component"
```

---

## Task 11: `InsightCard` component (replaces `CompanyChip`)

**Files:**
- Create: `frontend/src/components/InsightCard.tsx`
- Create: `frontend/src/components/InsightCard.test.tsx`
- Modify: `frontend/src/lib/i18n.ts`

**Interfaces:**
- Consumes: `CompanyLogo` (Task 8), `InsightSparkline` (Task 9), `InsightGauges` (Task 10), `formatRelativeTime` (Task 4), `getCompanyPrices` (existing, `frontend/src/lib/api.ts:279`), `eventTypeLabel` (existing, `frontend/src/lib/ruleLabels.ts:36`).
- Produces: `<InsightCard company={AlertCompany} eventType={string | null | undefined} alertCreatedAt={string} />`, consumed by Task 12 (`AlertCompanies`).
- Note: does NOT render `ReasoningPanel` inline (that content moves to Task 13's detail page) — clicking "Read full analysis" navigates via `<Link>`.

- [ ] **Step 1: Add the i18n keys**

In `frontend/src/lib/i18n.ts`, add these entries to `CATALOG`:

```ts
  'insights.seeMoreInsights': {
    en: '+ {n} more insights', hi: '+ {n} more insights', mr: '+ {n} more insights', gu: '+ {n} more insights',
    ml: '+ {n} more insights', te: '+ {n} more insights', ta: '+ {n} more insights', kn: '+ {n} more insights',
    pa: '+ {n} more insights', bn: '+ {n} more insights',
  },
  'insights.seeLess': {
    en: 'See less', hi: 'See less', mr: 'See less', gu: 'See less', ml: 'See less', te: 'See less',
    ta: 'See less', kn: 'See less', pa: 'See less', bn: 'See less',
  },
  'insights.readFullAnalysis': {
    en: 'Read full analysis', hi: 'Read full analysis', mr: 'Read full analysis', gu: 'Read full analysis',
    ml: 'Read full analysis', te: 'Read full analysis', ta: 'Read full analysis', kn: 'Read full analysis',
    pa: 'Read full analysis', bn: 'Read full analysis',
  },
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/components/InsightCard.test.tsx`:

```tsx
import { render as rtlRender, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import InsightCard from './InsightCard';
import type { AlertCompany } from '../lib/api';
import * as api from '../lib/api';
import { LanguageProvider } from '../lib/language';

function render(ui: ReactElement) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>{ui}</LanguageProvider>
    </MemoryRouter>,
  );
}

const company: AlertCompany = {
  company_id: 1,
  ticker: 'RELIANCE.NS',
  name: 'Reliance Industries',
  index_tier: 'NIFTY50',
  direction: 'bullish',
  magnitude_low: 2,
  magnitude_high: 4,
  rationale: 'Refiner margins expand on crude softness.',
  key_points: ['Crude softness widens refining margin.', 'Peer refiners saw similar moves last cycle.', 'Watch Brent for reversal risk.'],
  confidence_score: 84,
  time_horizon: 'Short-Term',
  basis: 'direct_mention',
  confidence: 'llm_estimate',
  market: 'IN',
  in_my_holdings: false,
  past_mentions: [],
  impact_level: 'direct',
};

beforeEach(() => {
  vi.spyOn(api, 'getCompanyPrices').mockResolvedValue({ period: '1mo', points: [], available: false });
});

describe('InsightCard', () => {
  it('shows the company name, ticker, and confidence gauge', () => {
    render(<InsightCard company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" />);
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
    expect(screen.getByText('84%')).toBeInTheDocument();
  });

  it('shows only the first key point as the summary by default', () => {
    render(<InsightCard company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" />);
    expect(screen.getByText('Crude softness widens refining margin.')).toBeInTheDocument();
    expect(screen.queryByText('Peer refiners saw similar moves last cycle.')).not.toBeInTheDocument();
  });

  it('expands remaining key points on "see more" and collapses on "see less"', async () => {
    render(<InsightCard company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" />);
    await userEvent.click(screen.getByText('+ 2 more insights'));
    expect(screen.getByText('Peer refiners saw similar moves last cycle.')).toBeInTheDocument();
    expect(screen.getByText('Watch Brent for reversal risk.')).toBeInTheDocument();

    await userEvent.click(screen.getByText('See less'));
    expect(screen.queryByText('Peer refiners saw similar moves last cycle.')).not.toBeInTheDocument();
  });

  it('does not show the see-more toggle when there is only one key point', () => {
    render(
      <InsightCard
        company={{ ...company, key_points: ['Only point.'] }}
        eventType="crude_oil"
        alertCreatedAt="2026-07-17T10:00:00.000Z"
      />,
    );
    expect(screen.queryByText(/more insights/)).not.toBeInTheDocument();
  });

  it('falls back to a truncated rationale when key_points is empty (legacy alert)', () => {
    render(
      <InsightCard
        company={{ ...company, key_points: [] }}
        eventType="crude_oil"
        alertCreatedAt="2026-07-17T10:00:00.000Z"
      />,
    );
    // Plain regex getByText substring-matches every ancestor's full
    // textContent too (RTL matches per-element, not just leaves), which
    // would throw "multiple elements found" here since the summary <p> is
    // nested inside several containers -- constrain the match to the <p>.
    expect(
      screen.getByText((_, el) => el?.tagName === 'P' && /Refiner margins expand/.test(el.textContent ?? '')),
    ).toBeInTheDocument();
  });

  it('links "Read full analysis" to the detail route', () => {
    render(<InsightCard company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" alertId={7} />);
    const link = screen.getByRole('link', { name: /read full analysis/i });
    expect(link).toHaveAttribute('href', '/alerts/7/company/1');
  });

  it('fetches and renders a sparkline when a price series is available', async () => {
    vi.spyOn(api, 'getCompanyPrices').mockResolvedValue({
      period: '1mo',
      points: [{ date: '2026-06-17', close: 100 }, { date: '2026-07-17', close: 110 }],
      available: true,
    });
    const { container } = render(
      <InsightCard company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" />,
    );
    await waitFor(() => expect(container.querySelector('svg')).not.toBeNull());
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/InsightCard.test.tsx`
Expected: FAIL with `Cannot find module './InsightCard'`

- [ ] **Step 4: Write the implementation**

Create `frontend/src/components/InsightCard.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { AlertCompany, PricePoint } from '../lib/api';
import { getCompanyPrices } from '../lib/api';
import { useLanguage } from '../lib/language';
import { eventTypeLabel } from '../lib/ruleLabels';
import { formatRelativeTime } from '../lib/relativeTime';
import CompanyLogo from './CompanyLogo';
import InsightSparkline from './InsightSparkline';
import InsightGauges from './InsightGauges';

function truncatedRationale(rationale: string): string {
  const firstSentence = rationale.split(/(?<=[.!?])\s+/)[0];
  if (firstSentence.length <= 160) return firstSentence;
  return `${firstSentence.slice(0, 157)}…`;
}

export default function InsightCard({
  company,
  eventType,
  alertCreatedAt,
  alertId,
}: {
  company: AlertCompany;
  eventType?: string | null;
  alertCreatedAt: string;
  alertId?: number;
}) {
  const { language, t } = useLanguage();
  const [expanded, setExpanded] = useState(false);
  const [points, setPoints] = useState<PricePoint[]>([]);

  useEffect(() => {
    let cancelled = false;
    getCompanyPrices(company.company_id, '1mo')
      .then((series) => {
        if (!cancelled && series.available) setPoints(series.points);
      })
      .catch(() => {
        // Sparkline is decorative context, not critical data -- degrade to
        // no chart rather than surfacing a fetch error in the feed.
      });
    return () => {
      cancelled = true;
    };
  }, [company.company_id]);

  const points_ = company.key_points.length > 0 ? company.key_points : [truncatedRationale(company.rationale)];
  const summary = points_[0];
  const extraPoints = points_.slice(1);

  const priceLine =
    company.price_at_analysis != null ? (
      <span className={company.direction === 'bearish' ? 'text-bearish' : 'text-bullish'}>
        <span aria-hidden="true">{company.direction === 'bearish' ? '▼' : '▲'}</span>{' '}
        <span className="font-data">
          {company.market === 'IN' ? '₹' : '$'}
          {company.price_at_analysis.toFixed(2)}
        </span>
        {company.return_1m != null && (
          <span className="font-data block text-right text-xs">
            {company.return_1m >= 0 ? '+' : ''}
            {company.return_1m.toFixed(1)}%
          </span>
        )}
      </span>
    ) : null;

  return (
    <div className="border-b border-hairline py-4 font-editorial">
      <div className="flex items-baseline justify-between font-data text-[11px] uppercase tracking-widest text-muted">
        <span>
          {eventType ? eventTypeLabel(eventType) : ''}
          {eventType && company.sector ? ' · ' : ''}
          {company.sector ?? ''}
        </span>
        <span>{formatRelativeTime(alertCreatedAt, new Date(), language)}</span>
      </div>

      <div className="mt-3 flex items-center gap-3.5">
        <CompanyLogo logoUrl={company.logo_url} ticker={company.ticker} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[22px] font-semibold leading-tight text-ink">{company.name}</p>
          <p className="font-data text-xs text-muted">{company.ticker}</p>
        </div>
        {priceLine && <div className="shrink-0 text-right text-base">{priceLine}</div>}
      </div>

      {points.length >= 2 && (
        <div className="mt-3">
          <InsightSparkline points={points} direction={company.direction} />
        </div>
      )}

      <InsightGauges
        confidenceScore={company.confidence_score}
        timeHorizon={company.time_horizon}
        impactLevel={company.impact_level}
      />

      <p className="mt-3 text-base leading-relaxed text-ink">{summary}</p>

      {expanded && extraPoints.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1.5 text-sm text-ink">
          {extraPoints.map((point, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-muted" aria-hidden="true">
                •
              </span>
              <span>{point}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex items-center justify-between font-data text-[11.5px]">
        {extraPoints.length > 0 ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-muted"
          >
            {expanded ? t('insights.seeLess') : t('insights.seeMoreInsights', { n: extraPoints.length })}
          </button>
        ) : (
          <span />
        )}
        {alertId != null && (
          <Link
            to={`/alerts/${alertId}/company/${company.company_id}`}
            className="uppercase tracking-widest text-ink underline"
          >
            {t('insights.readFullAnalysis')} →
          </Link>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/InsightCard.test.tsx`
Expected: All 7 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/InsightCard.tsx frontend/src/components/InsightCard.test.tsx frontend/src/lib/i18n.ts
git commit -m "feat: add InsightCard compact feed component"
```

---

## Task 12: Wire `InsightCard` into `AlertCompanies`

**Files:**
- Modify: `frontend/src/components/AlertCompanies.tsx`
- Modify: `frontend/src/components/AlertCompanies.test.tsx`

**Interfaces:**
- Consumes: `InsightCard` from Task 11.
- Produces: `AlertCompanies` renders a single-column feed of `InsightCard`s per group instead of a 2-column grid of `CompanyChip`s.

- [ ] **Step 1: Read the existing test file to know what to preserve**

Run: `cd frontend && cat src/components/AlertCompanies.test.tsx` (or use the Read tool) — this task's implementer must keep every existing assertion about tabs/group-mode/empty-states/keyboard-shortcut/charts-button passing; only the per-company rendering assertions (anything asserting on `CompanyChip`-specific markup) change to assert on `InsightCard`-specific markup instead (e.g. a rendered company name/ticker, not the chip's `role="button"` accordion trigger).

- [ ] **Step 2: Update the failing assertions**

In `frontend/src/components/AlertCompanies.test.tsx`, find every assertion that clicks a `CompanyChip` row to expand it (accordion-style) or asserts on `role="button"` chip semantics, and replace with an assertion that an `InsightCard`'s "Read full analysis" link is present with the correct `href` for that company — mirroring Task 11's own link-href test, not re-deriving new assertions. Any assertion purely about company name/ticker text rendering needs no change (both components render that text).

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/AlertCompanies.test.tsx`
Expected: FAIL — `CompanyChip`'s accordion-click assertions no longer match rendered output once Step 4 swaps the component.

- [ ] **Step 4: Swap the component and layout**

In `frontend/src/components/AlertCompanies.tsx`, replace the import:

```ts
import CompanyChip from './CompanyChip';
```

with:

```ts
import InsightCard from './InsightCard';
```

Replace the grid rendering block:

```tsx
            <div className="grid grid-cols-1 items-start gap-2 sm:grid-cols-2">
              {group.companies.map((company) => (
                <div
                  key={company.company_id}
                  className={groupMode !== 'tier' && company.basis === 'sector_inference' ? 'opacity-70' : undefined}
                >
                  <CompanyChip company={company} eventType={alert.event_type} />
                </div>
              ))}
            </div>
```

with a single-column feed (no `sm:grid-cols-2`, hairline dividers instead of grid gaps — `InsightCard` already draws its own bottom border, so no extra gap/divider class is needed here):

```tsx
            <div className="flex flex-col">
              {group.companies.map((company) => (
                <div
                  key={company.company_id}
                  className={groupMode !== 'tier' && company.basis === 'sector_inference' ? 'opacity-70' : undefined}
                >
                  <InsightCard
                    company={company}
                    eventType={alert.event_type}
                    alertCreatedAt={alert.created_at}
                    alertId={alert.id}
                  />
                </div>
              ))}
            </div>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/AlertCompanies.test.tsx`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/AlertCompanies.tsx frontend/src/components/AlertCompanies.test.tsx
git commit -m "feat: render the affected-companies feed as InsightCards"
```

---

## Task 13: `AlertCompanyAnalysisPage` (full detail page) + route

**Files:**
- Create: `frontend/src/pages/AlertCompanyAnalysisPage.tsx`
- Create: `frontend/src/pages/AlertCompanyAnalysisPage.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `getAlert(id)` (existing, `frontend/src/lib/api.ts:234`), `CompanyLogo` (Task 8), `InsightSparkline` (Task 9), `InsightGauges` (Task 10), `formatEvidenceRef`/`eventTypeLabel` (existing, `frontend/src/lib/ruleLabels.ts`), `MentionRow` (existing, unmodified).
- Produces: route `/alerts/:id/company/:companyId` rendering the full reasoning content currently in `ReasoningPanel`, restyled per the design spec (numbered reasons+evidence, plain mono risks/assumptions/unknowns lists, italic blockquote alternative view, single confidence fill bar + contributor/penalty list, Facts section, past mentions).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/AlertCompanyAnalysisPage.test.tsx`:

```tsx
import { render as rtlRender, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AlertCompanyAnalysisPage from './AlertCompanyAnalysisPage';
import * as api from '../lib/api';
import type { Alert } from '../lib/api';
import { LanguageProvider } from '../lib/language';

function render(ui: ReactElement, initialPath: string) {
  return rtlRender(
    <MemoryRouter initialEntries={[initialPath]}>
      <LanguageProvider>
        <Routes>
          <Route path="/alerts/:id/company/:companyId" element={ui} />
        </Routes>
      </LanguageProvider>
    </MemoryRouter>,
  );
}

const ALERT: Alert = {
  id: 7,
  category: 'oil_energy',
  category_label: 'Oil & Energy',
  created_at: '2026-07-17T10:00:00.000Z',
  article: { id: 1, title: 'Headline', url: 'https://example.com', image_url: null },
  event_type: 'crude_oil',
  companies: [
    {
      company_id: 1,
      ticker: 'RELIANCE.NS',
      name: 'Reliance Industries',
      index_tier: 'NIFTY50',
      direction: 'bullish',
      magnitude_low: 2,
      magnitude_high: 4,
      rationale: 'Refiner margins expand.',
      key_points: ['Refiner margins expand on crude softness.'],
      confidence_score: 84,
      time_horizon: 'Short-Term',
      basis: 'direct_mention',
      confidence: 'llm_estimate',
      market: 'IN',
      in_my_holdings: false,
      past_mentions: [],
      reasons: ['Crude softness lowers input costs.', 'Refining margins historically widen in this regime.'],
      evidence_refs: ['RULE_CRUDE_OIL_DROP', 'article:4471'],
      risks: ['Demand destruction could offset the margin gain.'],
      assumptions: ['Assumes crude stays below $70/bbl through the quarter.'],
      unknowns: [],
      alternative_hypothesis: 'If crude rebounds sharply, the margin thesis reverses.',
      confidence_contributors: ['Matched a known rulebook rule'],
      confidence_penalties: ['No historical calibration yet (2 samples, need 5)'],
      price_at_analysis: 1642.5,
      return_1m: 3.2,
      return_3m: 9.1,
      contradiction_note: null,
      impact_level: 'direct',
    },
  ],
};

describe('AlertCompanyAnalysisPage', () => {
  it('shows the company name, full reasons list, and evidence', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(ALERT);
    render(<AlertCompanyAnalysisPage />, '/alerts/7/company/1');

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.getByText('Crude softness lowers input costs.')).toBeInTheDocument();
    expect(screen.getByText('Refining margins historically widen in this regime.')).toBeInTheDocument();
  });

  it('shows risks, assumptions, and the alternative hypothesis', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(ALERT);
    render(<AlertCompanyAnalysisPage />, '/alerts/7/company/1');

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.getByText('Demand destruction could offset the margin gain.')).toBeInTheDocument();
    expect(screen.getByText('Assumes crude stays below $70/bbl through the quarter.')).toBeInTheDocument();
    expect(screen.getByText('If crude rebounds sharply, the margin thesis reverses.')).toBeInTheDocument();
  });

  it('shows confidence contributors and penalties', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(ALERT);
    render(<AlertCompanyAnalysisPage />, '/alerts/7/company/1');

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.getByText('Matched a known rulebook rule')).toBeInTheDocument();
    expect(screen.getByText('No historical calibration yet (2 samples, need 5)')).toBeInTheDocument();
  });

  it('shows the facts section with price and returns', async () => {
    // Price/returns render as adjacent leaf <span>s inside a shared div, so
    // a plain regex getByText would substring-match every ancestor's full
    // textContent too (RTL matches per-element, not just leaves) and throw
    // "multiple elements found" -- a leaf-only exact-text matcher sidesteps
    // that ambiguity entirely.
    vi.spyOn(api, 'getAlert').mockResolvedValue(ALERT);
    render(<AlertCompanyAnalysisPage />, '/alerts/7/company/1');

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(
      screen.getByText((_, el) => el?.tagName === 'SPAN' && el.textContent === '₹1642.50'),
    ).toBeInTheDocument();
    expect(
      screen.getByText((_, el) => el?.tagName === 'SPAN' && el.textContent === '+3.2% (1M)'),
    ).toBeInTheDocument();
  });

  it('shows a contradiction note with distinct treatment when present', async () => {
    const withContradiction: Alert = {
      ...ALERT,
      companies: [{ ...ALERT.companies[0], contradiction_note: 'Price down 8.3% over the past month despite bullish call.' }],
    };
    vi.spyOn(api, 'getAlert').mockResolvedValue(withContradiction);
    render(<AlertCompanyAnalysisPage />, '/alerts/7/company/1');

    await waitFor(() =>
      expect(screen.getByText('Price down 8.3% over the past month despite bullish call.')).toBeInTheDocument(),
    );
  });

  it('renders nothing crashing when the company id is not found in the alert', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(ALERT);
    render(<AlertCompanyAnalysisPage />, '/alerts/7/company/999');

    // Regex getByText would also match RTL's own render-container div here
    // (its textContent equals the single rendered <p>'s text in this
    // minimal tree) and throw "multiple elements found" -- constrain to <p>.
    await waitFor(() =>
      expect(
        screen.getByText((_, el) => el?.tagName === 'P' && /not found/i.test(el.textContent ?? '')),
      ).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/AlertCompanyAnalysisPage.test.tsx`
Expected: FAIL with `Cannot find module './AlertCompanyAnalysisPage'`

- [ ] **Step 3: Write the implementation**

Create `frontend/src/pages/AlertCompanyAnalysisPage.tsx`. Both `useEffect` calls are declared unconditionally, before either early `return` — the second effect internally no-ops until `company` resolves, so it does not violate the rules of hooks (an effect placed after an early `return null`/`return <p>...</p>` would be called on some renders and not others, which is the bug this avoids):

```tsx
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import type { Alert, AlertCompany, PricePoint } from '../lib/api';
import { getAlert, getCompanyPrices } from '../lib/api';
import { useLanguage } from '../lib/language';
import { eventTypeLabel, formatEvidenceRef } from '../lib/ruleLabels';
import CompanyLogo from '../components/CompanyLogo';
import InsightSparkline from '../components/InsightSparkline';
import InsightGauges from '../components/InsightGauges';
import MentionRow from '../components/MentionRow';

export default function AlertCompanyAnalysisPage() {
  const { id, companyId } = useParams<{ id: string; companyId: string }>();
  const { t } = useLanguage();
  const [alert, setAlert] = useState<Alert | null>(null);
  const [loading, setLoading] = useState(true);
  const [points, setPoints] = useState<PricePoint[]>([]);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    getAlert(Number(id))
      .then(setAlert)
      .finally(() => setLoading(false));
  }, [id]);

  const company: AlertCompany | undefined = alert?.companies.find(
    (c) => c.company_id === Number(companyId),
  );

  useEffect(() => {
    if (!company) return;
    let cancelled = false;
    getCompanyPrices(company.company_id, '3mo')
      .then((series) => {
        if (!cancelled && series.available) setPoints(series.points);
      })
      .catch(() => {
        // Sparkline is decorative context, not critical data -- degrade to
        // no chart rather than surfacing a fetch error on this page.
      });
    return () => {
      cancelled = true;
    };
  }, [company]);

  if (loading) return null;

  if (!alert || !company) {
    return <p className="mx-auto max-w-feed px-4 py-8 text-sm text-muted">Company not found in this alert.</p>;
  }

  const evidenceRefs = company.evidence_refs ?? [];
  const reasons = company.reasons ?? [];
  const risks = company.risks ?? [];
  const assumptions = company.assumptions ?? [];
  const unknowns = company.unknowns ?? [];
  const contributors = company.confidence_contributors ?? [];
  const penalties = company.confidence_penalties ?? [];

  return (
    <div className="mx-auto max-w-feed px-4 py-8 font-editorial">
      <p className="font-data text-[11px] uppercase tracking-widest text-muted">
        {alert.event_type ? eventTypeLabel(alert.event_type) : ''}
        {alert.event_type && company.sector ? ' · ' : ''}
        {company.sector ?? ''}
      </p>

      <div className="mt-3 flex items-center gap-4">
        <CompanyLogo logoUrl={company.logo_url} ticker={company.ticker} size="lg" />
        <div>
          <p className="text-[28px] font-semibold leading-tight text-ink">{company.name}</p>
          <p className="font-data text-xs text-muted">{company.ticker}</p>
        </div>
      </div>

      {points.length >= 2 && (
        <div className="mt-4">
          <InsightSparkline points={points} direction={company.direction} />
        </div>
      )}

      <InsightGauges
        confidenceScore={company.confidence_score}
        timeHorizon={company.time_horizon}
        impactLevel={company.impact_level}
      />

      <div className="mt-4 border-t border-hairline pt-3">
        <p className="font-data text-[10.5px] uppercase tracking-widest text-muted">Confidence</p>
        <div className="mt-1.5 h-0.5 w-full bg-hairline">
          <div className="h-full bg-bullish" style={{ width: `${company.confidence_score}%` }} />
        </div>
        {(contributors.length > 0 || penalties.length > 0) && (
          <ul className="mt-2 flex flex-col gap-1 font-data text-xs">
            {contributors.map((c, i) => (
              <li key={`c-${i}`} className="flex gap-2 text-bullish">
                <span aria-hidden="true">+</span>
                <span>{c}</span>
              </li>
            ))}
            {penalties.map((p, i) => (
              <li key={`p-${i}`} className="flex gap-2 text-bearish">
                <span aria-hidden="true">−</span>
                <span>{p}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {reasons.length > 0 && (
        <div className="mt-4 border-t border-hairline pt-3">
          <p className="font-data text-[10.5px] uppercase tracking-widest text-muted">Reasons &amp; evidence</p>
          <ol className="mt-2 flex flex-col gap-2 text-sm text-ink">
            {reasons.map((reason, i) => (
              <li key={i} className="flex gap-2">
                <span className="font-data text-muted">{i + 1}.</span>
                <div>
                  <p>{reason}</p>
                  {evidenceRefs[i] && (
                    <p className="font-data text-xs text-muted">{formatEvidenceRef(evidenceRefs[i]).text}</p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}

      {company.alternative_hypothesis && (
        <div className="mt-4 border-l-2 border-hairline pl-3.5 italic text-muted">
          <p className="mb-1 font-data text-[10.5px] uppercase not-italic tracking-widest text-muted">
            Alternative read
          </p>
          {company.alternative_hypothesis}
        </div>
      )}

      {(risks.length > 0 || assumptions.length > 0 || unknowns.length > 0) && (
        <div className="mt-4 border-t border-hairline pt-3">
          <p className="font-data text-[10.5px] uppercase tracking-widest text-muted">Risks, assumptions &amp; unknowns</p>
          <ul className="mt-2 flex flex-col gap-1 text-sm text-ink">
            {[...risks, ...assumptions, ...unknowns].map((item, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-muted" aria-hidden="true">•</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {company.price_at_analysis != null && (
        <div className="mt-4 border-t border-hairline pt-3">
          <p className="font-data text-[10.5px] uppercase tracking-widest text-muted">{t('reasoning.factsHeading')}</p>
          <div className="mt-1.5 font-data text-sm text-ink">
            <span>
              {company.market === 'IN' ? '₹' : '$'}
              {company.price_at_analysis.toFixed(2)}
            </span>
            {company.return_1m != null && (
              <span className={`ml-3 ${company.return_1m >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                {company.return_1m >= 0 ? '+' : ''}
                {company.return_1m.toFixed(1)}% (1M)
              </span>
            )}
            {company.return_3m != null && (
              <span className={`ml-3 ${company.return_3m >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                {company.return_3m >= 0 ? '+' : ''}
                {company.return_3m.toFixed(1)}% (3M)
              </span>
            )}
          </div>
          {company.contradiction_note && (
            <p className="mt-2 flex items-start gap-1.5 text-bearish">
              <span aria-hidden="true">⚠</span>
              <span>{company.contradiction_note}</span>
            </p>
          )}
        </div>
      )}

      {company.past_mentions.length > 0 && (
        <div className="mt-4 border-t border-hairline pt-3">
          <p className="font-data text-[10.5px] uppercase tracking-widest text-muted">{t('reasoning.previously')}</p>
          <ul className="mt-1.5 flex flex-col gap-1">
            {company.past_mentions.map((mention) => (
              <MentionRow key={mention.alert_id} mention={mention} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Add the route**

In `frontend/src/App.tsx`, add the import:

```ts
import AlertCompanyAnalysisPage from './pages/AlertCompanyAnalysisPage';
```

And add the route inside `<Routes>`, next to the existing `/alerts/:id/charts` route:

```tsx
        <Route path="/alerts/:id/charts" element={<AlertChartsPage />} />
        <Route path="/alerts/:id/company/:companyId" element={<AlertCompanyAnalysisPage />} />
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/AlertCompanyAnalysisPage.test.tsx`
Expected: All 6 tests PASS.

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: Existing App tests still PASS (route addition is additive).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/AlertCompanyAnalysisPage.tsx frontend/src/pages/AlertCompanyAnalysisPage.test.tsx frontend/src/App.tsx
git commit -m "feat: add full-analysis detail page and route"
```

---

## Task 14: Remove superseded components

**Files:**
- Delete: `frontend/src/components/CompanyChip.tsx`
- Delete: `frontend/src/components/CompanyChip.test.tsx`
- Delete: `frontend/src/components/ReasoningPanel.tsx`
- Delete: `frontend/src/components/ReasoningPanel.test.tsx`
- Delete: `frontend/src/components/CompanyAvatar.tsx`
- Delete: `frontend/src/components/CompanyAvatar.test.tsx`

**Interfaces:**
- Consumes: nothing new — this task only removes files once Task 12 (which was the last consumer of `CompanyChip`, which was the last consumer of `ReasoningPanel` and `CompanyAvatar`) has landed.

- [ ] **Step 1: Confirm nothing still imports the files to be deleted**

Run: `cd frontend && grep -rn "CompanyChip\|ReasoningPanel\|CompanyAvatar" src --include="*.tsx" --include="*.ts" | grep -v "\.test\.tsx"`
Expected: No output (zero non-test-file matches) — if any file still imports one of these, stop and resolve that reference before deleting (it means an earlier task's integration step was missed).

- [ ] **Step 2: Delete the files**

```bash
git rm frontend/src/components/CompanyChip.tsx frontend/src/components/CompanyChip.test.tsx
git rm frontend/src/components/ReasoningPanel.tsx frontend/src/components/ReasoningPanel.test.tsx
git rm frontend/src/components/CompanyAvatar.tsx frontend/src/components/CompanyAvatar.test.tsx
```

- [ ] **Step 3: Run the full frontend test suite**

Run: `cd frontend && npx vitest run`
Expected: All remaining tests PASS (0 failures, 0 references to the deleted files).

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: remove CompanyChip/ReasoningPanel/CompanyAvatar, superseded by InsightCard/AlertCompanyAnalysisPage/CompanyLogo"
```

---

## Task 15: Full backend test suite + final verification

**Files:** none (verification-only task).

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && python -m pytest -v`
Expected: All tests PASS (0 failures).

- [ ] **Step 2: Run the full frontend test suite and typecheck**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: All tests PASS, 0 type errors.

- [ ] **Step 3: Run the frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 4: Manual visual check (cannot be automated)**

Start the dev server (`npm run dev` in `frontend/`, backend running per the project's normal local-dev instructions) and visually confirm, per the design spec's "Explicitly out of scope" note:
- The compact `InsightCard` feed renders correctly in both light and dark theme (the design spec's light-theme token substitutions were never screen-checked in the visual companion — this is the first real check).
- A company with a real Brandfetch logo shows the image; a company with none shows the monogram fallback cleanly.
- The "see more insights" toggle expands/collapses correctly in the running app (not just in the vitest DOM).
- `/alerts/:id/company/:companyId` renders the full detail page correctly for a real alert with reasoning-engine data.

This step has no pass/fail automation — report what was checked and any visual issues found back to the user before considering this plan complete.
