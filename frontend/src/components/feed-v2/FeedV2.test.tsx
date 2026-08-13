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
    direction: 'negative',
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
