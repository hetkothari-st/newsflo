import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import ImpactBar from './ImpactBar';
import type { AlertCompany } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

function render(ui: ReactElement) {
  return rtlRender(<LanguageProvider>{ui}</LanguageProvider>);
}

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
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

  it('expands a ReasoningPanel when a bar is tapped', async () => {
    render(<ImpactBar companies={[company({ company_id: 1, rationale: 'Refiner margins widen on lower crude.' })]} />);
    await userEvent.click(screen.getByText('AAA'));
    expect(screen.getByText(/Refiner margins widen/)).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<ImpactBar companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('keeps the bar visibly non-zero for a lower-ranked company even with a long ticker name', () => {
    // Regression test for the bug where the OUTER row's width shrank per
    // rank, and a long ticker label at a low rank could squeeze the
    // flex-1 bar div down to 0px. jsdom doesn't do real layout, so we
    // can't measure rendered pixels -- instead we assert on the inline
    // style width we set directly on the bar segment, which is the
    // mechanism the fix relies on to guarantee visibility.
    const { container } = render(
      <ImpactBar
        companies={[
          company({ company_id: 1, ticker: 'HDFCBANK.NS', direction: 'bearish', magnitude_low: 9, magnitude_high: 10 }),
          company({ company_id: 2, ticker: 'SUNPHARMA.NS', direction: 'bearish', magnitude_low: 3, magnitude_high: 4 }),
        ]}
      />,
    );
    const bars = container.querySelectorAll('.bg-bearish');
    expect(bars).toHaveLength(2);
    const widths = Array.from(bars).map((el) => parseFloat((el as HTMLElement).style.width));
    // The bar for the lower-ranked (index 1) company must never be 0/NaN.
    expect(widths[1]).toBeGreaterThan(0);
    // Rank must still be visually distinguishable: stronger rank (index 0)
    // renders a clearly longer bar than the weaker rank (index 1).
    expect(widths[0]).toBeGreaterThan(widths[1]);
  });

  it('marks both the bar segment and the ticker label as flex-shrink: 0', () => {
    // jsdom doesn't do real flex layout, so an inline pixel width alone
    // can't be trusted as a regression test -- a real browser can still
    // shrink a `style.width` flex item toward its content-size floor when
    // its sibling (the ticker label, whose text can't wrap) resists
    // shrinking and the row is too narrow for both. `shrink-0` on BOTH
    // elements is what turns the pixel width into a genuine floor. Assert
    // the class itself is present, since that's the real mechanism.
    const { container } = render(
      <ImpactBar
        companies={[
          company({ company_id: 1, ticker: 'HDFCBANK.NS', direction: 'bearish', magnitude_low: 9, magnitude_high: 10 }),
          company({ company_id: 2, ticker: 'SUNPHARMA.NS', direction: 'bullish', magnitude_low: 3, magnitude_high: 4 }),
        ]}
      />,
    );

    const bearishBar = container.querySelector('.bg-bearish');
    const bullishBar = container.querySelector('.bg-bullish');
    expect(bearishBar).not.toBeNull();
    expect(bullishBar).not.toBeNull();
    expect(bearishBar).toHaveClass('shrink-0');
    expect(bullishBar).toHaveClass('shrink-0');

    const bearishLabel = screen.getByText('HDFCBANK.NS').closest('button');
    const bullishLabel = screen.getByText('SUNPHARMA.NS').closest('button');
    expect(bearishLabel).not.toBeNull();
    expect(bullishLabel).not.toBeNull();
    expect(bearishLabel).toHaveClass('shrink-0');
    expect(bullishLabel).toHaveClass('shrink-0');
  });
});
