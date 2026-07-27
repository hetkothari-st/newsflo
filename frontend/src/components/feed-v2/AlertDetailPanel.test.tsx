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
