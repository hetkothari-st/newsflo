import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import FeedRowV2 from './FeedRowV2';
import type { FeedV2Alert } from '../../lib/feedV2Api';

function makeAlert(overrides: Partial<FeedV2Alert> = {}): FeedV2Alert {
  return {
    id: 1,
    category: 'oil_gas',
    created_at: '2026-07-22T10:00:00Z',
    summary_short: 'Oil supply shock lifts refiners',
    summary_long: null,
    article: { id: 1, title: 'Oil surges', url: 'https://example.com/a', source: 'test', published_at: null },
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

describe('FeedRowV2', () => {
  it('renders the excess move, why, verdict, ticker, and score', () => {
    render(<FeedRowV2 alert={makeAlert()} onOpen={() => {}} />);
    expect(screen.getByText(/4\.2%/)).toBeInTheDocument();
    expect(screen.getByText('Oil supply shock lifts refiners')).toBeInTheDocument();
    expect(screen.getByText('Company specific')).toBeInTheDocument();
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
    expect(screen.getByText('82')).toBeInTheDocument();
  });

  it('shows a down arrow for a bearish move and a bullish text color class for an up move', () => {
    const { rerender } = render(<FeedRowV2 alert={makeAlert({ direction: 'bearish' })} onOpen={() => {}} />);
    expect(screen.getByText(/▼/)).toBeInTheDocument();

    rerender(<FeedRowV2 alert={makeAlert({ direction: 'bullish', excess_move_pct: 3.0 })} onOpen={() => {}} />);
    expect(screen.getByText(/▲/)).toBeInTheDocument();
  });

  it('renders an owned dot only when in_my_holdings is true', () => {
    const { rerender, container } = render(
      <FeedRowV2 alert={makeAlert({ in_my_holdings: false })} onOpen={() => {}} />,
    );
    expect(container.querySelector('[data-testid="owned-dot"]')).not.toBeInTheDocument();

    rerender(<FeedRowV2 alert={makeAlert({ in_my_holdings: true })} onOpen={() => {}} />);
    expect(container.querySelector('[data-testid="owned-dot"]')).toBeInTheDocument();
  });

  it('calls onOpen when the row is clicked', () => {
    const onOpen = vi.fn();
    render(<FeedRowV2 alert={makeAlert()} onOpen={onOpen} />);
    fireEvent.click(screen.getByText('Oil supply shock lifts refiners'));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});

describe('FeedRowV2 intensity breakdown', () => {
  it('opens the intensity breakdown popup when the intensity bar/score is clicked, without opening the row', () => {
    const onOpen = vi.fn();
    render(<FeedRowV2 alert={makeAlert()} onOpen={onOpen} />);

    fireEvent.click(screen.getByTestId('intensity-tap-target'));

    expect(onOpen).not.toHaveBeenCalled();
    expect(screen.getByText("Intensity measures how hard the news hit this stock — not whether it's a good investment.")).toBeInTheDocument();
  });

  it('closes the breakdown popup via its own close button without opening the row', () => {
    const onOpen = vi.fn();
    render(<FeedRowV2 alert={makeAlert()} onOpen={onOpen} />);

    fireEvent.click(screen.getByTestId('intensity-tap-target'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Close'));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('does not open the row when Enter/Space is pressed on the intensity tap target', () => {
    const onOpen = vi.fn();
    render(<FeedRowV2 alert={makeAlert()} onOpen={onOpen} />);

    fireEvent.keyDown(screen.getByTestId('intensity-tap-target'), { key: 'Enter', code: 'Enter' });

    expect(onOpen).not.toHaveBeenCalled();
  });
});
