import { render, screen } from '@testing-library/react';
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
    // Both the mobile carousel and desktop grid render a card per alert (CSS
    // toggles which is visible; jsdom doesn't evaluate media queries), so
    // each title matches twice -- assert on the count rather than a single element.
    expect((await screen.findAllByText('India oil headline')).length).toBeGreaterThan(0);
    expect(screen.queryAllByText('Global tech headline')).toHaveLength(0);

    await userEvent.click(screen.getByRole('tab', { name: /global/i }));
    expect((await screen.findAllByText('Global tech headline')).length).toBeGreaterThan(0);
    expect(screen.queryAllByText('India oil headline')).toHaveLength(0);
  });

  it('opens AlertDetail with the company breakdown when a card is clicked', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    renderFeed();
    await screen.findAllByText('India oil headline');
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
    await screen.findAllByText('India oil headline');

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
    expect(screen.queryAllByText('Live oil headline')).toHaveLength(0);

    await userEvent.click(screen.getByText('1 new'));
    // Same carousel/grid duplication as above -- assert on the count.
    expect((await screen.findAllByText('Live oil headline')).length).toBeGreaterThan(0);
    expect(screen.queryByText('1 new')).not.toBeInTheDocument();
  });
});
