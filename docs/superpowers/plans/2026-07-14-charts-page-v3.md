# Dedicated Charts Page (v3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the disliked `CompanyTree.tsx` SVG tree with a dedicated full-screen charts page (`/alerts/:id/charts`) reached by swiping right off an alert, showing 4 real chart forms (treemap, grouped bars, diverging bar, donut) built from data the pipeline already produces.

**Architecture:** New backend `GET /api/alerts/{id}` endpoint (data source for a direct page load). New frontend route + page with a 4-way horizontal pager, each pane a standalone chart component consuming the existing `AlertCompany[]` shape. Entry via a new `useHorizontalSwipe` touch hook (mobile) and a Charts button/keyboard shortcut (desktop), both replacing the removed List/Chart toggle in `AlertCompanies.tsx`.

**Tech Stack:** FastAPI/SQLAlchemy (backend), React 18 + TypeScript + react-router-dom + Tailwind (frontend), Vitest + @testing-library/react (frontend tests), pytest (backend tests). No new dependencies — all charts are plain HTML/CSS/SVG, no charting library.

## Global Constraints

- No magnitude percentage is ever printed as a raw number anywhere on the charts page (matches `ReasoningPanel`'s existing "overstates precision" rule).
- Bar/rank sizing uses **per-alert relative rank** (`rankByMagnitude`), never a fixed global threshold — see `docs/superpowers/specs/2026-07-14-charts-page-v3-design.md` for why (observed magnitude values span ~0-100 with no fixed scale).
- Bullish/bearish always render via the existing `text-bullish`/`text-bearish`/`bg-bullish`/`bg-bearish` Tailwind tokens — never a new ad hoc color.
- Sector color: fixed-order palette keyed to the real `Company.sector` values (confirmed in the local DB: `oil_gas, banking, auto, it, pharma, fmcg, metals, telecom, infra, other`), not the old hash-based `sectorColor()`. Validate with the `dataviz` skill's `scripts/validate_palette.js` for both light and dark chart surfaces before the branch is considered done.
- Every alert has at most 5 companies (pipeline cap) — every chart is small-N by construction; no chart needs pagination/virtualization within itself.
- `CompanyTree.tsx` and `CompanyTree.test.tsx` are deleted, not refactored.
- Dark/light theme support follows the existing `theme-light:` Tailwind variant pattern used throughout (`AlertCompanies.tsx`, `CompanyChip.tsx`).

---

### Task 1: Backend — `GET /api/alerts/{id}` endpoint

**Files:**
- Modify: `backend/app/routers/alerts.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Produces: `GET /api/alerts/{alert_id}` — same per-alert JSON shape as one entry of `GET /api/alerts`'s array (see existing `list_alerts` response shape). 404 with `{"detail": "..."}` if `alert_id` doesn't exist.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py`:

```python
def test_get_alert_by_id_returns_same_shape_as_list_alerts(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(
        source="test", url="https://example.com/single", title="Single alert headline",
        status="ANALYZED", category="oil_energy", image_url="https://example.com/single.jpg",
    )
    db_session.add(article)
    db_session.commit()

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        key_points_json='["Crude prices ease", "Refining margins widen"]',
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    list_response = client.get("/api/alerts")
    single_response = client.get(f"/api/alerts/{alert.id}")

    assert single_response.status_code == 200
    assert single_response.json() == list_response.json()[0]

    app.dependency_overrides.clear()


def test_get_alert_by_id_404s_for_missing_alert(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    response = client.get("/api/alerts/999999")

    assert response.status_code == 404

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_api.py -k get_alert_by_id -v`
Expected: FAIL with 404 (route not defined) on the first test, since `GET /api/alerts/{id}` doesn't exist yet.

- [ ] **Step 3: Extract `_serialize_alert` and add the route**

Replace the entire contents of `backend/app/routers/alerts.py` with the following — it extracts the per-alert dict construction (currently inline in `list_alerts`'s `result = []` loop) into a standalone `_serialize_alert` function shared by both routes, and adds the new `GET /{alert_id}` route:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_current_user_optional
from app.companies.history import bulk_past_mentions, mentions_before
from app.companies.market import infer_market
from app.i18n import get_lang
from app.models import Alert, AlertCompany, Holding, User
from app.pipeline import decode_key_points
from app.routers.articles import get_db
from app.translation.lookup import (
    bulk_alert_company_translations,
    bulk_article_titles,
    bulk_category_labels,
)

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# The feed has no use for unbounded history, and returning every alert ever
# created means this endpoint's response size (and, before the eager-loading
# fix below, its query count) grows forever as alerts accumulate.
ALERTS_LIMIT = 200


def _serialize_alert(
    alert: Alert,
    held_company_ids: set[int],
    article_titles: dict[int, str],
    ac_translations: dict[int, tuple[str, list[str]]],
    category_labels: dict[str, str],
    mentions_index,
) -> dict:
    companies = []
    for ac in alert.companies:
        rationale, key_points = ac_translations.get(ac.id, (ac.rationale, decode_key_points(ac)))
        companies.append({
            "company_id": ac.company_id, "ticker": ac.company.ticker, "name": ac.company.name,
            "index_tier": ac.company.index_tier, "sector": ac.company.sector, "direction": ac.direction,
            "magnitude_low": ac.magnitude_low, "magnitude_high": ac.magnitude_high,
            "rationale": rationale, "key_points": key_points,
            "basis": ac.basis, "confidence": ac.confidence,
            "market": infer_market(ac.company.ticker),
            "in_my_holdings": ac.company_id in held_company_ids,
            "past_mentions": mentions_before(mentions_index, ac.company_id, alert.created_at),
        })
    return {
        "id": alert.id,
        # `category` stays the raw, canonical, untranslated slug -- it's
        # a matching/storage key (watchlist filtering, color swatch
        # lookup), not just display text. `category_label` is the
        # additive, purely-for-display translated field.
        "category": alert.category,
        "category_label": category_labels.get(alert.category, alert.category),
        "created_at": alert.created_at.isoformat(),
        "article": {
            "id": alert.article.id,
            "title": article_titles.get(alert.article_id, alert.article.title),
            "url": alert.article.url,
            "image_url": alert.article.image_url,
        },
        "companies": companies,
    }


def _held_company_ids(db: Session, current_user: User | None) -> set[int]:
    # Anonymous requests get an empty set -> every company is in_my_holdings=False.
    if current_user is None:
        return set()
    return {h.company_id for h in db.query(Holding).filter_by(user_id=current_user.id).all()}


@router.get("")
def list_alerts(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
    lang: str = Depends(get_lang),
):
    held_company_ids = _held_company_ids(db, current_user)

    # selectinload replaces what used to be one lazy-load query per alert for
    # .article, one per alert for .companies, and one per AlertCompany for
    # .company -- each collapses into a single batched IN-query regardless
    # of how many alerts/companies are in this page.
    alerts = (
        db.query(Alert)
        .options(
            selectinload(Alert.article),
            selectinload(Alert.companies).selectinload(AlertCompany.company),
        )
        .order_by(Alert.created_at.desc())
        .limit(ALERTS_LIMIT)
        .all()
    )

    # Four bulk lookups total, regardless of alert count, keyed by lang for
    # the first three -- empty dicts (and every .get() below falling back to
    # English) when lang == "en" or nothing's been translated yet.
    article_titles = bulk_article_titles(db, [a.article_id for a in alerts], lang)
    ac_translations = bulk_alert_company_translations(
        db, [ac.id for a in alerts for ac in a.companies], lang
    )
    category_labels = bulk_category_labels(db, list({a.category for a in alerts}), lang)
    mentions_index = bulk_past_mentions(db, {ac.company_id for a in alerts for ac in a.companies})

    return [
        _serialize_alert(alert, held_company_ids, article_titles, ac_translations, category_labels, mentions_index)
        for alert in alerts
    ]


@router.get("/{alert_id}")
def get_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
    lang: str = Depends(get_lang),
):
    alert = (
        db.query(Alert)
        .options(
            selectinload(Alert.article),
            selectinload(Alert.companies).selectinload(AlertCompany.company),
        )
        .filter(Alert.id == alert_id)
        .first()
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    held_company_ids = _held_company_ids(db, current_user)
    article_titles = bulk_article_titles(db, [alert.article_id], lang)
    ac_translations = bulk_alert_company_translations(db, [ac.id for ac in alert.companies], lang)
    category_labels = bulk_category_labels(db, [alert.category], lang)
    mentions_index = bulk_past_mentions(db, {ac.company_id for ac in alert.companies})

    return _serialize_alert(alert, held_company_ids, article_titles, ac_translations, category_labels, mentions_index)
```

Note: `/{alert_id}` is registered after `""` — FastAPI matches `GET /api/alerts` (no path param) against the bare route regardless of declaration order since they're structurally different paths, so ordering here doesn't matter, but keep list before single for readability.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_api.py -v`
Expected: all `test_api.py` tests PASS, including the two new ones.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass (196+ tests), no regressions in `test_pipeline.py`/`test_history.py` from the refactor.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/alerts.py backend/tests/test_api.py
git commit -m "feat: add GET /api/alerts/{id} for direct charts-page loads"
```

---

### Task 2: Frontend — `getAlert` API client function

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Produces: `getAlert(id: number, token: string | null, lang: Language): Promise<Alert>`

- [ ] **Step 1: Add the function**

In `frontend/src/lib/api.ts`, immediately after `getAlerts`:

```typescript
export async function getAlert(id: number, token: string | null = null, lang: Language = 'en'): Promise<Alert> {
  const res = await fetch(`/api/alerts/${id}?lang=${lang}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Alert;
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npm run typecheck` (or `npx tsc --noEmit` if no dedicated script — check `package.json` `scripts` first)
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add getAlert client for the single-alert endpoint"
```

---

### Task 3: Frontend — fixed sector palette + labels

**Files:**
- Modify: `frontend/src/features/visualize/colors.ts`
- Modify: `frontend/src/features/visualize/colors.test.ts`
- Modify: `frontend/src/features/visualize/transforms.ts` (sector label lookup)
- Modify: `frontend/src/features/visualize/transforms.test.ts`

**Interfaces:**
- Produces: `sectorColor(sector: string): string` (same signature, new fixed-order implementation), `SECTOR_LABEL: Record<string, string>` and `sectorLabel(sector: string): string` in `transforms.ts`.
- Consumes: real `Company.sector` values confirmed in this codebase's data: `oil_gas`, `banking`, `auto`, `it`, `pharma`, `fmcg`, `metals`, `telecom`, `infra`, `other`.

- [ ] **Step 1: Write the failing tests**

Replace `frontend/src/features/visualize/colors.test.ts` entirely with:

```typescript
import { describe, expect, it } from 'vitest';
import { sectorColor } from './colors';

describe('sectorColor', () => {
  it('assigns a fixed color to each known sector, not a hash', () => {
    expect(sectorColor('oil_gas')).toBe(sectorColor('oil_gas'));
    expect(sectorColor('banking')).not.toBe(sectorColor('oil_gas'));
  });

  it('returns a hex color string for every known sector', () => {
    const known = ['oil_gas', 'banking', 'auto', 'it', 'pharma', 'fmcg', 'metals', 'telecom', 'infra', 'other'];
    for (const sector of known) {
      expect(sectorColor(sector)).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it('assigns every known sector a distinct color', () => {
    const known = ['oil_gas', 'banking', 'auto', 'it', 'pharma', 'fmcg', 'metals', 'telecom', 'infra', 'other'];
    const colors = new Set(known.map(sectorColor));
    expect(colors.size).toBe(known.length);
  });

  it('falls back to a defined color for an unrecognized sector string', () => {
    expect(sectorColor('some_future_sector')).toMatch(/^#[0-9A-Fa-f]{6}$/);
    expect(sectorColor('some_future_sector')).toBe(sectorColor('another_unknown'));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/colors.test.ts`
Expected: FAIL — "assigns every known sector a distinct color" fails against the old hash implementation (hash collisions across 10 sectors into an 8-color palette are likely, and even without a collision the test is checking a property the hash function doesn't guarantee).

- [ ] **Step 3: Replace `colors.ts` with a fixed-order palette**

Replace `frontend/src/features/visualize/colors.ts` entirely:

```typescript
// Fixed-order categorical palette, one color per known Company.sector value
// (confirmed against real data: oil_gas, banking, auto, it, pharma, fmcg,
// metals, telecom, infra, other -- see backend/app/analysis/schemas.py's
// SECTORS enum, which Company.sector is seeded from). A hash-based palette
// (the old approach) doesn't guarantee distinct colors and isn't validated
// for colorblind-safety; a fixed assignment does both by construction --
// validate with the dataviz skill's scripts/validate_palette.js before
// shipping any change to these hex values.
const SECTOR_COLOR: Record<string, string> = {
  oil_gas: '#E85D4C',
  banking: '#4A90D9',
  auto: '#F5A623',
  it: '#2DD4BF',
  pharma: '#9B7EDE',
  fmcg: '#5FB878',
  metals: '#8C7355',
  telecom: '#D4708C',
  infra: '#6C8CD5',
  other: '#8A8F98',
};

const FALLBACK_COLOR = '#8A8F98';

export function sectorColor(sector: string): string {
  return SECTOR_COLOR[sector] ?? FALLBACK_COLOR;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/colors.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Add human-readable sector labels to `transforms.ts`**

`groupBySector` currently sets `label: sector` (the raw slug, e.g. `"oil_gas"`) — add a label map and use it, matching the existing `TIER_LABEL` pattern in the same file. In `frontend/src/features/visualize/transforms.ts`, add after `TIER_LABEL`:

```typescript
const SECTOR_LABEL: Record<string, string> = {
  oil_gas: 'Oil & Gas',
  banking: 'Banking',
  auto: 'Auto',
  it: 'IT',
  pharma: 'Pharma',
  fmcg: 'FMCG',
  metals: 'Metals',
  telecom: 'Telecom',
  infra: 'Infrastructure',
  other: 'Other',
};

export function sectorLabel(sector: string): string {
  return SECTOR_LABEL[sector] ?? sector;
}
```

Then change `groupBySector`'s map call:

```typescript
  return [...bySector.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([sector, group]) => ({
      key: sector,
      label: sectorLabel(sector),
      color: sectorColor(sector),
      companies: group,
    }));
```

- [ ] **Step 6: Add a test for `sectorLabel`**

Add to `frontend/src/features/visualize/transforms.test.ts` (find the existing `describe('groupBySector', ...)` block and add a sibling `describe`):

```typescript
describe('sectorLabel', () => {
  it('maps known sector slugs to a human-readable label', () => {
    expect(sectorLabel('oil_gas')).toBe('Oil & Gas');
    expect(sectorLabel('it')).toBe('IT');
  });

  it('falls back to the raw string for an unrecognized sector', () => {
    expect(sectorLabel('some_future_sector')).toBe('some_future_sector');
  });
});
```

Also update the import line at the top of `transforms.test.ts` to include `sectorLabel` alongside whatever's already imported from `./transforms`.

- [ ] **Step 7: Run the full frontend test suite**

Run: `cd frontend && npx vitest run`
Expected: all tests pass, including `transforms.test.ts`'s existing `groupBySector` tests (check whether any existing assertion hardcodes a raw-slug label like `'oil_gas'` as the expected `label` — if so, update that assertion to the new human-readable label, since this is the intended behavior change).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/visualize/colors.ts frontend/src/features/visualize/colors.test.ts frontend/src/features/visualize/transforms.ts frontend/src/features/visualize/transforms.test.ts
git commit -m "feat: fixed validated sector palette and human-readable sector labels"
```

- [ ] **Step 9: Validate the palette**

Run the dataviz skill's validator against the 10 hex values in `SECTOR_COLOR` (in the order listed) for both `--mode light` and `--mode dark`, using this repo's actual light/dark chart-surface colors (check `frontend/tailwind.config` or `frontend/src/index.css` for the `page`/`surface` CSS variable values in each theme). If anything FAILs, adjust the failing hex value(s) in `SECTOR_COLOR` and re-run until both modes pass, then amend the commit.

---

### Task 4: Frontend — `rankByMagnitude`

**Files:**
- Modify: `frontend/src/features/visualize/transforms.ts`
- Modify: `frontend/src/features/visualize/transforms.test.ts`

**Interfaces:**
- Produces: `rankByMagnitude(companies: AlertCompany[]): AlertCompany[]`

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/features/visualize/transforms.test.ts`:

```typescript
describe('rankByMagnitude', () => {
  it('sorts descending by the midpoint of magnitude_low and magnitude_high', () => {
    const weak = company({ company_id: 1, magnitude_low: 0, magnitude_high: 1 });
    const strong = company({ company_id: 2, magnitude_low: 8, magnitude_high: 12 });
    const mid = company({ company_id: 3, magnitude_low: 2, magnitude_high: 4 });

    expect(rankByMagnitude([weak, strong, mid]).map((c) => c.company_id)).toEqual([2, 3, 1]);
  });

  it('keeps input order for equal midpoints (stable sort)', () => {
    const a = company({ company_id: 1, magnitude_low: 1, magnitude_high: 3 });
    const b = company({ company_id: 2, magnitude_low: 0, magnitude_high: 4 });

    expect(rankByMagnitude([a, b]).map((c) => c.company_id)).toEqual([1, 2]);
  });

  it('returns an empty array for an empty input', () => {
    expect(rankByMagnitude([])).toEqual([]);
  });

  it('returns a single-element array unchanged', () => {
    const only = company({ company_id: 1 });
    expect(rankByMagnitude([only])).toEqual([only]);
  });
});
```

Check the top of `transforms.test.ts` for an existing `company(overrides)` fixture helper (the same pattern used in `SentimentBar.test.tsx`) — if `transforms.test.ts` doesn't already have one, add it matching that same shape, and import `rankByMagnitude` in the top import line.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/features/visualize/transforms.test.ts`
Expected: FAIL — `rankByMagnitude` is not exported yet.

- [ ] **Step 3: Implement**

Add to `frontend/src/features/visualize/transforms.ts`:

```typescript
function magnitudeMidpoint(company: AlertCompany): number {
  return (company.magnitude_low + company.magnitude_high) / 2;
}

// Ordinal ranking, not a claim about absolute scale -- magnitude_low/high
// values span roughly 0-100 with no fixed calibration, so this only ever
// answers "stronger than the others in THIS alert's company list," never
// "this company moved N%." See docs/superpowers/specs/2026-07-14-charts-page-v3-design.md.
export function rankByMagnitude(companies: AlertCompany[]): AlertCompany[] {
  return [...companies].sort((a, b) => magnitudeMidpoint(b) - magnitudeMidpoint(a));
}
```

(`Array.prototype.sort` is stable per the ES2019 spec, satisfying the tie-break test.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/features/visualize/transforms.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/transforms.ts frontend/src/features/visualize/transforms.test.ts
git commit -m "feat: add rankByMagnitude for per-alert relative chart sizing"
```

---

### Task 5: Frontend — `useHorizontalSwipe` hook

**Files:**
- Create: `frontend/src/lib/useHorizontalSwipe.ts`
- Test: `frontend/src/lib/useHorizontalSwipe.test.tsx`

**Interfaces:**
- Produces: `useHorizontalSwipe(handlers: { onSwipeLeft?: () => void; onSwipeRight?: () => void }): { onTouchStart, onTouchMove, onTouchEnd }` — a set of React touch event handlers to spread onto any element.
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/useHorizontalSwipe.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useHorizontalSwipe } from './useHorizontalSwipe';

function Swipeable({ onSwipeLeft, onSwipeRight }: { onSwipeLeft?: () => void; onSwipeRight?: () => void }) {
  const handlers = useHorizontalSwipe({ onSwipeLeft, onSwipeRight });
  return <div data-testid="target" {...handlers} />;
}

function touch(clientX: number, clientY: number) {
  return { touches: [{ clientX, clientY }] } as unknown as React.TouchEvent;
}

describe('useHorizontalSwipe', () => {
  it('fires onSwipeRight when the horizontal drag exceeds the threshold, moving right', () => {
    const onSwipeRight = vi.fn();
    render(<Swipeable onSwipeRight={onSwipeRight} />);
    const target = screen.getByTestId('target');

    target.dispatchEvent(Object.assign(new Event('touchstart', { bubbles: true }), { touches: [{ clientX: 0, clientY: 0 }] }));
    target.dispatchEvent(Object.assign(new Event('touchmove', { bubbles: true }), { touches: [{ clientX: 80, clientY: 5 }] }));
    target.dispatchEvent(new Event('touchend', { bubbles: true }));

    expect(onSwipeRight).toHaveBeenCalledTimes(1);
  });

  it('fires onSwipeLeft when the horizontal drag exceeds the threshold, moving left', () => {
    const onSwipeLeft = vi.fn();
    render(<Swipeable onSwipeLeft={onSwipeLeft} />);
    const target = screen.getByTestId('target');

    target.dispatchEvent(Object.assign(new Event('touchstart', { bubbles: true }), { touches: [{ clientX: 100, clientY: 0 }] }));
    target.dispatchEvent(Object.assign(new Event('touchmove', { bubbles: true }), { touches: [{ clientX: 10, clientY: 5 }] }));
    target.dispatchEvent(new Event('touchend', { bubbles: true }));

    expect(onSwipeLeft).toHaveBeenCalledTimes(1);
  });

  it('does not fire when the drag is vertical-dominant', () => {
    const onSwipeRight = vi.fn();
    const onSwipeLeft = vi.fn();
    render(<Swipeable onSwipeRight={onSwipeRight} onSwipeLeft={onSwipeLeft} />);
    const target = screen.getByTestId('target');

    target.dispatchEvent(Object.assign(new Event('touchstart', { bubbles: true }), { touches: [{ clientX: 0, clientY: 0 }] }));
    target.dispatchEvent(Object.assign(new Event('touchmove', { bubbles: true }), { touches: [{ clientX: 30, clientY: 120 }] }));
    target.dispatchEvent(new Event('touchend', { bubbles: true }));

    expect(onSwipeRight).not.toHaveBeenCalled();
    expect(onSwipeLeft).not.toHaveBeenCalled();
  });

  it('does not fire when the horizontal drag is below the threshold', () => {
    const onSwipeRight = vi.fn();
    render(<Swipeable onSwipeRight={onSwipeRight} />);
    const target = screen.getByTestId('target');

    target.dispatchEvent(Object.assign(new Event('touchstart', { bubbles: true }), { touches: [{ clientX: 0, clientY: 0 }] }));
    target.dispatchEvent(Object.assign(new Event('touchmove', { bubbles: true }), { touches: [{ clientX: 10, clientY: 0 }] }));
    target.dispatchEvent(new Event('touchend', { bubbles: true }));

    expect(onSwipeRight).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/useHorizontalSwipe.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `frontend/src/lib/useHorizontalSwipe.ts`:

```typescript
import { useRef } from 'react';
import type { TouchEvent } from 'react';

// Fires at most one of onSwipeLeft/onSwipeRight per gesture, on touchend,
// once the horizontal drag clears both an absolute threshold AND the
// vertical delta -- so this never fires mid-gesture (no premature nav
// while the user is still deciding) and never fights a vertical
// scroll/scroll-snap gesture on the same element (see AlertCoverCard's
// MobileFeedCarousel, which relies on native vertical snap-scroll).
const THRESHOLD_PX = 60;

export function useHorizontalSwipe(handlers: { onSwipeLeft?: () => void; onSwipeRight?: () => void }) {
  const start = useRef<{ x: number; y: number } | null>(null);

  function onTouchStart(e: TouchEvent) {
    const touch = e.touches[0];
    start.current = { x: touch.clientX, y: touch.clientY };
  }

  function onTouchMove() {
    // Position is read fresh from the touchend event instead of tracked
    // here -- only touchstart's origin needs to persist between calls.
  }

  function onTouchEnd(e: TouchEvent) {
    const origin = start.current;
    start.current = null;
    if (!origin) return;
    const touch = e.changedTouches[0];
    if (!touch) return;
    const dx = touch.clientX - origin.x;
    const dy = touch.clientY - origin.y;
    if (Math.abs(dx) < THRESHOLD_PX || Math.abs(dx) <= Math.abs(dy)) return;
    if (dx > 0) handlers.onSwipeRight?.();
    else handlers.onSwipeLeft?.();
  }

  return { onTouchStart, onTouchMove, onTouchEnd };
}
```

Note: the test dispatches a `touchmove` before `touchend` to simulate a realistic gesture, but the implementation only reads `touchstart`'s origin and `touchend`'s final position — this is intentional (simpler, and immune to intermediate jitter); the `onTouchMove` handler is a placeholder for symmetry with `onTouchStart`/`onTouchEnd` so all three can be spread onto an element uniformly.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/useHorizontalSwipe.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/useHorizontalSwipe.ts frontend/src/lib/useHorizontalSwipe.test.tsx
git commit -m "feat: add useHorizontalSwipe touch gesture hook"
```

---

### Task 6: Frontend — `SectorTreemap` chart

**Files:**
- Create: `frontend/src/features/visualize/charts/SectorTreemap.tsx`
- Test: `frontend/src/features/visualize/charts/SectorTreemap.test.tsx`

**Interfaces:**
- Consumes: `groupBySector(companies: AlertCompany[]): CompanyGroup[]` (Task 3's updated version), `CompanyGroup` type from `../transforms`.
- Produces: `export default function SectorTreemap({ companies }: { companies: AlertCompany[] }): JSX.Element`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/charts/SectorTreemap.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SectorTreemap from './SectorTreemap';
import type { AlertCompany } from '../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50', sector: 'oil_gas',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('SectorTreemap', () => {
  it('renders one tile per sector present, labeled with the human-readable name', () => {
    render(
      <SectorTreemap
        companies={[
          company({ company_id: 1, sector: 'oil_gas', ticker: 'RIL' }),
          company({ company_id: 2, sector: 'banking', ticker: 'HDFCBANK', direction: 'bearish' }),
        ]}
      />,
    );
    expect(screen.getByText('Oil & Gas')).toBeInTheDocument();
    expect(screen.getByText('Banking')).toBeInTheDocument();
    expect(screen.getByText('RIL')).toBeInTheDocument();
    expect(screen.getByText('HDFCBANK')).toBeInTheDocument();
  });

  it('expands a ReasoningPanel when a company is tapped', () => {
    render(<SectorTreemap companies={[company({ company_id: 1, rationale: 'Refiner margins widen on lower crude.' })]} />);
    screen.getByText('AAA').click();
    expect(screen.getByText(/Refiner margins widen/)).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<SectorTreemap companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/SectorTreemap.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/charts/SectorTreemap.tsx`:

```typescript
import { useState } from 'react';
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { groupBySector } from '../transforms';

export default function SectorTreemap({ companies }: { companies: AlertCompany[] }) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const groups = groupBySector(companies);

  if (groups.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {groups.map((group) => (
          <div
            key={group.key}
            className="flex flex-col gap-2 rounded-lg border border-hairline bg-surface p-3 theme-light:border-transparent theme-light:shadow-neu-sm"
            style={{ borderTop: `3px solid ${group.color}` }}
          >
            <p className="text-xs uppercase tracking-widest text-muted">{group.label}</p>
            <div className="flex flex-wrap gap-1.5">
              {group.companies.map((company) => {
                const bullish = company.direction === 'bullish';
                return (
                  <button
                    key={company.company_id}
                    type="button"
                    onClick={() => setSelectedId((id) => (id === company.company_id ? null : company.company_id))}
                    className="flex items-center gap-1 rounded-md bg-page px-2 py-1 text-xs text-ink hover:border-muted"
                  >
                    <span className={bullish ? 'text-bullish' : 'text-bearish'} aria-hidden="true">
                      {bullish ? '▲' : '▼'}
                    </span>
                    {company.ticker}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      {selectedId !== null &&
        (() => {
          const selected = companies.find((c) => c.company_id === selectedId);
          return selected ? <ReasoningPanel company={selected} /> : null;
        })()}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/SectorTreemap.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/SectorTreemap.tsx frontend/src/features/visualize/charts/SectorTreemap.test.tsx
git commit -m "feat: add SectorTreemap chart"
```

---

### Task 7: Frontend — `TierRows` chart

**Files:**
- Create: `frontend/src/features/visualize/charts/TierRows.tsx`
- Test: `frontend/src/features/visualize/charts/TierRows.test.tsx`

**Interfaces:**
- Consumes: `groupByTier(companies: AlertCompany[]): CompanyGroup[]` (unchanged from existing `transforms.ts`).
- Produces: `export default function TierRows({ companies }: { companies: AlertCompany[] }): JSX.Element`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/charts/TierRows.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import TierRows from './TierRows';
import type { AlertCompany } from '../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('TierRows', () => {
  it('renders one row per tier present, with a net-bullish arrow when bullish outnumbers bearish', () => {
    render(
      <TierRows
        companies={[
          company({ company_id: 1, index_tier: 'NIFTY50', direction: 'bullish' }),
          company({ company_id: 2, index_tier: 'NIFTY50', direction: 'bullish', ticker: 'BBB' }),
          company({ company_id: 3, index_tier: 'NIFTY50', direction: 'bearish', ticker: 'CCC' }),
        ]}
      />,
    );
    expect(screen.getByText('Nifty 50')).toBeInTheDocument();
    expect(screen.getByLabelText('Net bullish')).toBeInTheDocument();
  });

  it('shows a neutral indicator when a tier is evenly split', () => {
    render(
      <TierRows
        companies={[
          company({ company_id: 1, index_tier: 'NIFTY50', direction: 'bullish' }),
          company({ company_id: 2, index_tier: 'NIFTY50', direction: 'bearish', ticker: 'BBB' }),
        ]}
      />,
    );
    expect(screen.getByLabelText('Evenly split')).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<TierRows companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/TierRows.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/charts/TierRows.tsx`:

```typescript
import { useState } from 'react';
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { groupByTier } from '../transforms';

function netSentiment(companies: AlertCompany[]): 'bullish' | 'bearish' | 'even' {
  const bullish = companies.filter((c) => c.direction === 'bullish').length;
  const bearish = companies.filter((c) => c.direction === 'bearish').length;
  if (bullish === bearish) return 'even';
  return bullish > bearish ? 'bullish' : 'bearish';
}

export default function TierRows({ companies }: { companies: AlertCompany[] }) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const groups = groupByTier(companies);

  if (groups.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      {groups.map((group) => {
        const net = netSentiment(group.companies);
        return (
          <div
            key={group.key}
            className="flex flex-col gap-2 rounded-lg border border-hairline bg-surface p-3 theme-light:border-transparent theme-light:shadow-neu-sm"
          >
            <div className="flex items-center justify-between">
              <p className="text-xs uppercase tracking-widest text-muted">{group.label}</p>
              {net === 'even' ? (
                <span aria-label="Evenly split" className="text-xs text-muted">
                  ▬
                </span>
              ) : (
                <span aria-label={net === 'bullish' ? 'Net bullish' : 'Net bearish'} className={net === 'bullish' ? 'text-bullish' : 'text-bearish'}>
                  {net === 'bullish' ? '▲' : '▼'}
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {group.companies.map((company) => {
                const bullish = company.direction === 'bullish';
                return (
                  <button
                    key={company.company_id}
                    type="button"
                    onClick={() => setSelectedId((id) => (id === company.company_id ? null : company.company_id))}
                    className="flex items-center gap-1 rounded-md bg-page px-2 py-1 text-xs text-ink hover:border-muted"
                  >
                    <span className={bullish ? 'text-bullish' : 'text-bearish'} aria-hidden="true">
                      {bullish ? '▲' : '▼'}
                    </span>
                    {company.ticker}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
      {selectedId !== null &&
        (() => {
          const selected = companies.find((c) => c.company_id === selectedId);
          return selected ? <ReasoningPanel company={selected} /> : null;
        })()}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/TierRows.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/TierRows.tsx frontend/src/features/visualize/charts/TierRows.test.tsx
git commit -m "feat: add TierRows chart"
```

---

### Task 8: Frontend — `ImpactBar` chart (diverging winners/losers)

**Files:**
- Create: `frontend/src/features/visualize/charts/ImpactBar.tsx`
- Test: `frontend/src/features/visualize/charts/ImpactBar.test.tsx`

**Interfaces:**
- Consumes: `rankByMagnitude(companies: AlertCompany[]): AlertCompany[]` (Task 4).
- Produces: `export default function ImpactBar({ companies }: { companies: AlertCompany[] }): JSX.Element`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/charts/ImpactBar.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ImpactBar from './ImpactBar';
import type { AlertCompany } from '../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('ImpactBar', () => {
  it('renders every company direct-labeled by ticker, split by direction', () => {
    render(
      <ImpactBar
        companies={[
          company({ company_id: 1, ticker: 'WINNER', direction: 'bullish', magnitude_low: 8, magnitude_high: 12 }),
          company({ company_id: 2, ticker: 'LOSER', direction: 'bearish', magnitude_low: 4, magnitude_high: 6 }),
        ]}
      />,
    );
    expect(screen.getByText('WINNER')).toBeInTheDocument();
    expect(screen.getByText('LOSER')).toBeInTheDocument();
  });

  it('never prints a raw magnitude number', () => {
    render(<ImpactBar companies={[company({ magnitude_low: 8.5, magnitude_high: 12.25 })]} />);
    expect(screen.queryByText(/8\.5/)).not.toBeInTheDocument();
    expect(screen.queryByText(/12\.25/)).not.toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('expands a ReasoningPanel when a bar is tapped', () => {
    render(<ImpactBar companies={[company({ company_id: 1, rationale: 'Refiner margins widen on lower crude.' })]} />);
    screen.getByText('AAA').click();
    expect(screen.getByText(/Refiner margins widen/)).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<ImpactBar companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/ImpactBar.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/charts/ImpactBar.tsx`:

```typescript
import { useState } from 'react';
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { rankByMagnitude } from '../transforms';

// Bar length comes from rank position within this side only (index 0 =
// nearest the axis = strongest in this alert), never from the raw
// magnitude float -- see rankByMagnitude's docstring.
function widthForRank(index: number, total: number): number {
  if (total <= 1) return 100;
  return 100 - (index / total) * 60;
}

function Bar({ company, side, onSelect }: { company: AlertCompany; side: 'left' | 'right'; onSelect: () => void }) {
  const bullish = company.direction === 'bullish';
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex items-center gap-2 text-xs ${side === 'left' ? 'flex-row-reverse' : ''}`}
    >
      <span className={bullish ? 'text-bullish' : 'text-bearish'} aria-hidden="true">
        {bullish ? '▲' : '▼'}
      </span>
      <span className="text-ink">{company.ticker}</span>
    </button>
  );
}

export default function ImpactBar({ companies }: { companies: AlertCompany[] }) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const bullish = rankByMagnitude(companies.filter((c) => c.direction === 'bullish'));
  const bearish = rankByMagnitude(companies.filter((c) => c.direction === 'bearish'));

  if (bullish.length === 0 && bearish.length === 0) return null;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col items-end gap-2">
          {bearish.map((company, i) => (
            <div key={company.company_id} className="flex items-center justify-end gap-2" style={{ width: `${widthForRank(i, bearish.length)}%` }}>
              <div className="h-2 flex-1 rounded-l-full bg-bearish" />
              <Bar company={company} side="left" onSelect={() => setSelectedId((id) => (id === company.company_id ? null : company.company_id))} />
            </div>
          ))}
        </div>
        <div className="flex flex-col items-start gap-2">
          {bullish.map((company, i) => (
            <div key={company.company_id} className="flex items-center gap-2" style={{ width: `${widthForRank(i, bullish.length)}%` }}>
              <Bar company={company} side="right" onSelect={() => setSelectedId((id) => (id === company.company_id ? null : company.company_id))} />
              <div className="h-2 flex-1 rounded-r-full bg-bullish" />
            </div>
          ))}
        </div>
      </div>
      {selectedId !== null &&
        (() => {
          const selected = companies.find((c) => c.company_id === selectedId);
          return selected ? <ReasoningPanel company={selected} /> : null;
        })()}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/ImpactBar.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/ImpactBar.tsx frontend/src/features/visualize/charts/ImpactBar.test.tsx
git commit -m "feat: add ImpactBar diverging winners/losers chart"
```

---

### Task 9: Frontend — `SplitDonut` chart

**Files:**
- Create: `frontend/src/features/visualize/charts/SplitDonut.tsx`
- Test: `frontend/src/features/visualize/charts/SplitDonut.test.tsx`

**Interfaces:**
- Consumes: `rankByMagnitude` (Task 4).
- Produces: `export default function SplitDonut({ companies }: { companies: AlertCompany[] }): JSX.Element`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/charts/SplitDonut.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SplitDonut from './SplitDonut';
import type { AlertCompany } from '../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('SplitDonut', () => {
  it('shows the bullish/bearish count split', () => {
    render(
      <SplitDonut
        companies={[
          company({ company_id: 1, direction: 'bullish' }),
          company({ company_id: 2, direction: 'bullish', ticker: 'BBB' }),
          company({ company_id: 3, direction: 'bearish', ticker: 'CCC' }),
        ]}
      />,
    );
    expect(screen.getByText('2 Bullish')).toBeInTheDocument();
    expect(screen.getByText('1 Bearish')).toBeInTheDocument();
  });

  it('lists companies ranked, bullish first then bearish', () => {
    render(
      <SplitDonut
        companies={[
          company({ company_id: 1, ticker: 'WEAK_BULL', direction: 'bullish', magnitude_low: 1, magnitude_high: 2 }),
          company({ company_id: 2, ticker: 'STRONG_BEAR', direction: 'bearish', magnitude_low: 20, magnitude_high: 30 }),
        ]}
      />,
    );
    const items = screen.getAllByRole('button').map((el) => el.textContent);
    expect(items.indexOf('WEAK_BULL')).toBeLessThan(items.indexOf('STRONG_BEAR'));
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<SplitDonut companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/features/visualize/charts/SplitDonut.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/charts/SplitDonut.tsx`:

```typescript
import { useState } from 'react';
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { rankByMagnitude } from '../transforms';

const RADIUS = 40;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export default function SplitDonut({ companies }: { companies: AlertCompany[] }) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const bullish = companies.filter((c) => c.direction === 'bullish');
  const bearish = companies.filter((c) => c.direction === 'bearish');
  const total = bullish.length + bearish.length;

  if (total === 0) return null;

  const bullishFraction = bullish.length / total;
  const bullishDash = bullishFraction * CIRCUMFERENCE;
  const ranked = [...rankByMagnitude(bullish), ...rankByMagnitude(bearish)];

  return (
    <div className="flex flex-col items-center gap-4 p-4">
      <svg viewBox="0 0 100 100" className="h-40 w-40 -rotate-90">
        <circle cx="50" cy="50" r={RADIUS} fill="none" strokeWidth="10" className="stroke-bearish" />
        {bullish.length > 0 && (
          <circle
            cx="50"
            cy="50"
            r={RADIUS}
            fill="none"
            strokeWidth="10"
            strokeLinecap="round"
            className="stroke-bullish"
            strokeDasharray={`${bullishDash} ${CIRCUMFERENCE - bullishDash}`}
          />
        )}
      </svg>
      <p className="text-xs">
        <span className="text-bullish">{bullish.length} Bullish</span>
        <span className="text-muted"> · </span>
        <span className="text-bearish">{bearish.length} Bearish</span>
      </p>
      <div className="flex w-full flex-col gap-1.5">
        {ranked.map((company) => {
          const isBullish = company.direction === 'bullish';
          return (
            <button
              key={company.company_id}
              type="button"
              onClick={() => setSelectedId((id) => (id === company.company_id ? null : company.company_id))}
              className="flex items-center gap-2 rounded-md border border-hairline bg-page px-2 py-1.5 text-left text-xs text-ink"
            >
              <span className={isBullish ? 'text-bullish' : 'text-bearish'} aria-hidden="true">
                {isBullish ? '▲' : '▼'}
              </span>
              {company.ticker}
            </button>
          );
        })}
      </div>
      {selectedId !== null &&
        (() => {
          const selected = companies.find((c) => c.company_id === selectedId);
          return selected ? <ReasoningPanel company={selected} /> : null;
        })()}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/features/visualize/charts/SplitDonut.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/charts/SplitDonut.tsx frontend/src/features/visualize/charts/SplitDonut.test.tsx
git commit -m "feat: add SplitDonut positive/negative composition chart"
```

---

### Task 10: Frontend — `AlertChartsPage` + route

**Files:**
- Create: `frontend/src/pages/AlertChartsPage.tsx`
- Test: `frontend/src/pages/AlertChartsPage.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `getAlert` (Task 2), `useHorizontalSwipe` (Task 5), `SectorTreemap`/`TierRows`/`ImpactBar`/`SplitDonut` (Tasks 6-9), `useAuth` (existing, from `../lib/auth`), `useLanguage` (existing, from `../lib/language`).
- Produces: default-exported `AlertChartsPage` component; registers route `/alerts/:id/charts` in `App.tsx`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/AlertChartsPage.test.tsx`. First check `frontend/src/pages/HoldingsPage.test.tsx` (or any existing page test) for how this codebase mocks `../lib/api` and wraps a page in a `MemoryRouter` with a route param — mirror that exact mocking pattern. Then write:

```typescript
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import AlertChartsPage from './AlertChartsPage';
import * as api from '../lib/api';
import type { Alert } from '../lib/api';

function alert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 1,
    category: 'oil_energy',
    category_label: 'Oil & Energy',
    created_at: '2026-07-14T00:00:00Z',
    article: { id: 1, title: 'Crude prices ease on supply news', url: 'https://example.com', image_url: null },
    companies: [
      {
        company_id: 1, ticker: 'RIL', name: 'Reliance Industries', index_tier: 'NIFTY50', sector: 'oil_gas',
        direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'Refiner margins widen.',
        key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
        in_my_holdings: false, past_mentions: [],
      },
    ],
    ...overrides,
  };
}

function renderPage(id = '1') {
  return render(
    <MemoryRouter initialEntries={[`/alerts/${id}/charts`]}>
      <Routes>
        <Route path="/alerts/:id/charts" element={<AlertChartsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('AlertChartsPage', () => {
  it('fetches the alert by route id and shows the article title', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');
    await waitFor(() => expect(screen.getByText('Crude prices ease on supply news')).toBeInTheDocument());
  });

  it('shows the pager labels for all four chart types', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');
    await waitFor(() => expect(screen.getByText('Sector')).toBeInTheDocument());
    expect(screen.getByText('Tier')).toBeInTheDocument();
    expect(screen.getByText('Impact')).toBeInTheDocument();
    expect(screen.getByText('Split')).toBeInTheDocument();
  });

  it('advances to the next chart type when the pager control is clicked', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');
    await waitFor(() => expect(screen.getByText('RIL')).toBeInTheDocument());
    screen.getByText('Tier').click();
    // Tier view renders the same company under a tier-row label instead of a sector tile.
    expect(screen.getByText('Nifty 50')).toBeInTheDocument();
  });

  it('shows an error state when the fetch fails', async () => {
    vi.spyOn(api, 'getAlert').mockRejectedValue(new Error('Alert not found'));
    renderPage('999');
    await waitFor(() => expect(screen.getByText('Alert not found')).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/AlertChartsPage.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the page**

Create `frontend/src/pages/AlertChartsPage.tsx`:

```typescript
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getAlert, type Alert } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
import { useHorizontalSwipe } from '../lib/useHorizontalSwipe';
import SectorTreemap from '../features/visualize/charts/SectorTreemap';
import TierRows from '../features/visualize/charts/TierRows';
import ImpactBar from '../features/visualize/charts/ImpactBar';
import SplitDonut from '../features/visualize/charts/SplitDonut';

const CHARTS = [
  { key: 'sector', label: 'Sector', Component: SectorTreemap },
  { key: 'tier', label: 'Tier', Component: TierRows },
  { key: 'impact', label: 'Impact', Component: ImpactBar },
  { key: 'split', label: 'Split', Component: SplitDonut },
] as const;

export default function AlertChartsPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { token } = useAuth();
  const { language } = useLanguage();
  const [alert, setAlert] = useState<Alert | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (!id) return;
    let active = true;
    getAlert(Number(id), token, language)
      .then((data) => {
        if (active) setAlert(data);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'Failed to load alert.');
      });
    return () => {
      active = false;
    };
  }, [id, token, language]);

  const swipeHandlers = useHorizontalSwipe({
    onSwipeLeft: () => setIndex((i) => Math.min(i + 1, CHARTS.length - 1)),
    onSwipeRight: () => (index === 0 ? navigate(-1) : setIndex((i) => Math.max(i - 1, 0))),
  });

  if (error) {
    return <p className="p-4 text-xs uppercase tracking-widest text-bearish">{error}</p>;
  }
  if (!alert) {
    return <p className="p-4 text-xs uppercase tracking-widest text-muted">Loading…</p>;
  }

  const { Component } = CHARTS[index];

  return (
    <div className="flex min-h-screen flex-col bg-page" {...swipeHandlers}>
      <div className="flex items-center gap-3 border-b border-hairline p-4">
        <button type="button" onClick={() => navigate(-1)} aria-label="Back" className="text-muted hover:text-ink">
          ←
        </button>
        <h1 className="truncate text-sm text-ink">{alert.article.title}</h1>
      </div>
      <div className="flex gap-4 border-b border-hairline px-4 py-2">
        {CHARTS.map((chart, i) => (
          <button
            key={chart.key}
            type="button"
            onClick={() => setIndex(i)}
            className={`text-xs uppercase tracking-widest ${i === index ? 'text-ink' : 'text-muted'}`}
          >
            {chart.label}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto">
        <Component companies={alert.companies} />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Register the route**

In `frontend/src/App.tsx`, add the import and route:

```typescript
import AlertChartsPage from './pages/AlertChartsPage';
```

Add inside `<Routes>`, alongside the existing routes:

```typescript
<Route path="/alerts/:id/charts" element={<AlertChartsPage />} />
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/AlertChartsPage.test.tsx`
Expected: PASS (4 tests). If the mocking pattern from Step 1 doesn't match this codebase's actual convention (found while reading `HoldingsPage.test.tsx`), adjust the test to match — the assertions above are what matter, not the exact mock syntax.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/AlertChartsPage.tsx frontend/src/pages/AlertChartsPage.test.tsx frontend/src/App.tsx
git commit -m "feat: add AlertChartsPage with 4-way chart pager and /alerts/:id/charts route"
```

---

### Task 11: Frontend — remove the old chart toggle, add Charts entry point, delete `CompanyTree`

**Files:**
- Modify: `frontend/src/components/AlertCompanies.tsx`
- Delete: `frontend/src/features/visualize/CompanyTree.tsx`
- Delete: `frontend/src/features/visualize/CompanyTree.test.tsx`
- Test: `frontend/src/components/AlertCompanies.test.tsx` (update existing tests)

**Interfaces:**
- Consumes: `useNavigate` from `react-router-dom`.
- Produces: `AlertCompanies` gains a Charts button (navigates to `/alerts/${alert.id}/charts`) with a right-arrow keyboard shortcut; loses `ViewMode`/chart rendering entirely.

- [ ] **Step 1: Read the existing test file**

Read `frontend/src/components/AlertCompanies.test.tsx` in full first — it almost certainly has tests asserting the List/Chart toggle exists and that clicking "Chart" renders `CompanyTree` (or its `aria-label`). Those tests need to be replaced, not left failing.

- [ ] **Step 2: Update `AlertCompanies.tsx`**

In `frontend/src/components/AlertCompanies.tsx`:
- Remove the `ViewMode` type, the `viewMode` state, the List/Chart toggle button group (lines ~97-110 in the current file), and the `CompanyTree` import + its conditional render branch (the `viewMode === 'chart' ? <CompanyTree .../> : grouped.map(...)` — keep only the `grouped.map(...)` branch, unconditionally).
- Add `import { useNavigate } from 'react-router-dom';` and remove `import CompanyTree from '../features/visualize/CompanyTree';`.
- Add a Charts button rendered next to the Group-by select (same row, so it doesn't need new layout), wired to `useNavigate()` to `/alerts/${alert.id}/charts`, hidden when `visible.length === 0`. Add a `keydown` listener (mirroring the pattern already in `AlertCoverCard.tsx`'s `Escape` handler) for `ArrowRight` triggering the same navigation.

The button:

```typescript
const navigate = useNavigate();
// ...
{visible.length > 0 && (
  <button
    type="button"
    onClick={() => navigate(`/alerts/${alert.id}/charts`)}
    className="flex items-center gap-1 rounded-md border border-hairline bg-surface px-2 py-1 text-xs uppercase tracking-widest text-ink theme-light:border-transparent theme-light:shadow-neu-sm"
  >
    {t('companies.charts')}
    <span aria-hidden="true">→</span>
  </button>
)}
```

Add the keyboard shortcut effect near the top of the component body:

```typescript
useEffect(() => {
  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'ArrowRight' && visible.length > 0) navigate(`/alerts/${alert.id}/charts`);
  }
  document.addEventListener('keydown', onKeyDown);
  return () => document.removeEventListener('keydown', onKeyDown);
}, [alert.id, visible.length, navigate]);
```

(Add `useEffect` to the existing `import { useState } from 'react';` line → `import { useEffect, useState } from 'react';`.)

Check `frontend/src/lib/i18n.ts` for the `TranslationKey` union and existing `companies.*` keys (e.g. `companies.list`, `companies.chart` which is being removed) — add `companies.charts: 'Charts'` (and its translations in whatever language-key structure `i18n.ts` uses) alongside them, removing `companies.list`/`companies.chart` if they're now unused (grep the codebase first to confirm nothing else references them).

- [ ] **Step 3: Update `AlertCompanies.test.tsx`**

Replace any test asserting the List/Chart toggle or `CompanyTree` rendering with a test asserting the Charts button navigates correctly. Since `AlertCompanies` isn't itself wrapped in a Router in its current tests (check the existing file), wrap the render in a `MemoryRouter` if it isn't already, and assert `screen.getByText('Charts')` (or the translated label) is present when `visible.length > 0` and absent when the active tab's list is empty.

- [ ] **Step 4: Delete `CompanyTree`**

```bash
rm frontend/src/features/visualize/CompanyTree.tsx frontend/src/features/visualize/CompanyTree.test.tsx
```

- [ ] **Step 5: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all tests pass. Fix any other file still importing `CompanyTree` (grep for `CompanyTree` across `frontend/src` to confirm none remain) or referencing the removed `companies.list`/`companies.chart` i18n keys.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/AlertCompanies.tsx frontend/src/components/AlertCompanies.test.tsx frontend/src/lib/i18n.ts
git rm frontend/src/features/visualize/CompanyTree.tsx frontend/src/features/visualize/CompanyTree.test.tsx
git commit -m "feat: replace chart toggle with Charts entry point, delete CompanyTree"
```

---

### Task 12: Frontend — swipe-right entry from feed cards

**Files:**
- Modify: `frontend/src/components/AlertCoverCard.tsx`
- Modify: `frontend/src/components/AlertCoverCard.test.tsx`

**Interfaces:**
- Consumes: `useHorizontalSwipe` (Task 5), `useNavigate` from `react-router-dom`.

- [ ] **Step 1: Read the existing test file**

Read `frontend/src/components/AlertCoverCard.test.tsx` in full to match its existing render/props conventions (it likely renders with a mock `onOpen`/`onClose` and doesn't currently wrap in a Router — check for a `MemoryRouter` wrapper or add one).

- [ ] **Step 2: Write the failing test**

Add to `frontend/src/components/AlertCoverCard.test.tsx` (adjust the fixture/import style to match the file's existing conventions):

```typescript
it('navigates to the charts page on a right swipe (collapsed card)', () => {
  const navigateSpy = vi.fn();
  vi.spyOn(routerDom, 'useNavigate').mockReturnValue(navigateSpy);
  render(<AlertCoverCard alert={testAlert} onOpen={vi.fn()} variant="carousel" />);
  const card = screen.getByRole('button');
  fireTouchSwipe(card, { fromX: 0, toX: 100 });
  expect(navigateSpy).toHaveBeenCalledWith(`/alerts/${testAlert.id}/charts`);
});
```

Where `fireTouchSwipe` is a small local helper dispatching `touchstart`/`touchend` with the given `clientX` values (mirroring the raw `dispatchEvent` pattern from `useHorizontalSwipe.test.tsx` in Task 5) — add it at the top of this test file if the file doesn't already have an equivalent. If mocking `useNavigate` via `vi.spyOn` doesn't fit this codebase's existing mocking convention (check how other component tests using `react-router-dom` hooks are mocked, e.g. `Feed.test.tsx` or similar), match whatever pattern they use instead.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/AlertCoverCard.test.tsx`
Expected: FAIL — no swipe handling wired up yet.

- [ ] **Step 4: Wire up the hook**

In `frontend/src/components/AlertCoverCard.tsx`, add:

```typescript
import { useNavigate } from 'react-router-dom';
import { useHorizontalSwipe } from '../lib/useHorizontalSwipe';
```

Inside the component body:

```typescript
const navigate = useNavigate();
const swipeHandlers = useHorizontalSwipe({
  onSwipeRight: () => navigate(`/alerts/${alert.id}/charts`),
});
```

Spread `{...swipeHandlers}` onto the root `<div>` in both the `expanded` branch (the `ref={cardRef}` div) and the un-expanded carousel-variant branch (the final `return` block's root div) — NOT the `grid` variant, which is desktop-only and has no touch entry per the design spec.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/AlertCoverCard.test.tsx`
Expected: PASS, including all pre-existing tests in this file (no regressions).

- [ ] **Step 6: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/AlertCoverCard.tsx frontend/src/components/AlertCoverCard.test.tsx
git commit -m "feat: wire swipe-right-to-charts on mobile feed cards"
```

---

### Task 13: Palette validation + full-branch visual verification

**Files:** none (verification-only task)

- [ ] **Step 1: Validate the sector palette**

If not already done as part of Task 3 Step 9, run the `dataviz` skill's `scripts/validate_palette.js` against the final `SECTOR_COLOR` hex values (from `frontend/src/features/visualize/colors.ts`) for both `--mode light` and `--mode dark`, using this app's actual chart-surface colors. Fix and re-commit if anything FAILs.

- [ ] **Step 2: Start a local dev server and seed test data**

Start the frontend/backend dev servers (following whatever pattern was used earlier in this project for local Playwright verification — an isolated port, seeded via a Python script creating a Company/Article/Alert/AlertCompany fixture set covering: multiple sectors, multiple tiers, both directions, at least one alert with only 1 company and one with 5).

- [ ] **Step 3: Playwright visual verification**

Using the Playwright MCP tools, navigate to the feed, verify:
- Swipe-right (or the desktop Charts button) opens `/alerts/:id/charts`.
- All 4 chart types render correctly for a multi-company alert, in both light and dark theme, at mobile width (390px) and desktop width.
- Sector treemap colors are visually distinct across all sectors present in the seed data.
- Impact bar never shows a raw percentage.
- Tapping a company in any chart expands its `ReasoningPanel`.
- The single-company and empty-adjacent (e.g., all-bullish, zero-bearish) edge cases render without visual breakage (no empty donut half, no zero-width bar).
- Direct navigation to a charts URL (paste into address bar / reload) loads correctly via `GET /api/alerts/{id}`.

Take screenshots at each of these checkpoints. Do not report this feature as visually complete without this step — this is the exact bar the previous two chart attempts failed to clear before being called "bad."

- [ ] **Step 4: Fix any visual issues found, then re-verify**

Iterate Steps 2-3 until clean, committing fixes as they're made.

---

## Execution Handoff

After all 13 tasks are complete and verified, use **superpowers:finishing-a-development-branch** to merge/push per the user's choice.
