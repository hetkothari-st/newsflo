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

  it('expands a ReasoningPanel when a bar is tapped', async () => {
    render(<ImpactBar companies={[company({ company_id: 1, rationale: 'Refiner margins widen on lower crude.' })]} />);
    await userEvent.click(screen.getByText('AAA'));
    expect(screen.getByText(/Refiner margins widen/)).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<ImpactBar companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
