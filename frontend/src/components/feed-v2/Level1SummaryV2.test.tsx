import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import Level1SummaryV2 from './Level1SummaryV2';
import type { FeedV2Alert } from '../../lib/feedV2Api';

function makeAlert(overrides: Partial<FeedV2Alert> = {}): FeedV2Alert {
  return {
    id: 1,
    category: 'oil_gas',
    created_at: '2026-07-22T10:00:00Z',
    summary_short: 'Oil supply shock lifts refiners',
    summary_long: 'Crude prices jumped on a supply disruption. Refiners face wider margin pressure.',
    article: { id: 1, title: 'Oil surges', url: 'https://example.com/a', source: 'Economic Times', published_at: '2026-07-22T09:45:00Z' },
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
    ...overrides,
  };
}

describe('Level1SummaryV2', () => {
  it('renders the two-sentence summary and verdict', () => {
    render(<Level1SummaryV2 alert={makeAlert()} />);
    expect(screen.getByText(/Crude prices jumped on a supply disruption/)).toBeInTheDocument();
    expect(screen.getByText('Company specific')).toBeInTheDocument();
  });

  it('renders raw and sector move as a metric tile', () => {
    render(<Level1SummaryV2 alert={makeAlert()} />);
    expect(screen.getByText(/-4\.8%/)).toBeInTheDocument();
    expect(screen.getByText(/-0\.6%/)).toBeInTheDocument();
  });

  it('renders volume multiple when present, omits it when null', () => {
    const { rerender } = render(<Level1SummaryV2 alert={makeAlert({ volume_multiple: 3.1 })} />);
    expect(screen.getByText(/3\.1/)).toBeInTheDocument();

    rerender(<Level1SummaryV2 alert={makeAlert({ volume_multiple: null })} />);
    expect(screen.queryByText(/average volume/)).not.toBeInTheDocument();
  });

  it('shows the Nifty 50 fallback note when is_fallback_benchmark is true', () => {
    render(<Level1SummaryV2 alert={makeAlert({ is_fallback_benchmark: true })} />);
    expect(screen.getByText(/vs Nifty 50/)).toBeInTheDocument();
  });

  it('shows the sector-index note when is_fallback_benchmark is false', () => {
    render(<Level1SummaryV2 alert={makeAlert({ is_fallback_benchmark: false })} />);
    expect(screen.getByText(/vs sector index/)).toBeInTheDocument();
  });

  it('renders source', () => {
    render(<Level1SummaryV2 alert={makeAlert()} />);
    expect(screen.getByText(/Economic Times/)).toBeInTheDocument();
  });

  it('renders a formatted created_at timestamp', () => {
    render(<Level1SummaryV2 alert={makeAlert({ created_at: '2026-07-22T10:00:00Z' })} />);
    const timeEl = document.querySelector('time');
    expect(timeEl).toBeInTheDocument();
    expect(timeEl).toHaveAttribute('dateTime', '2026-07-22T10:00:00Z');
    expect(timeEl?.textContent).toMatch(/Jul/);
  });

  it('renders a + prefix for positive raw and sector move values', () => {
    render(<Level1SummaryV2 alert={makeAlert({ raw_move_pct: 2.3, sector_move_pct: 0.9 })} />);
    expect(screen.getByText(/\+2\.3%/)).toBeInTheDocument();
    expect(screen.getByText(/\+0\.9%/)).toBeInTheDocument();
  });
});
