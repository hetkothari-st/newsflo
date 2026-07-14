import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import TierRows from './TierRows';
import type { AlertCompany } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

function render(ui: ReactElement) {
  return rtlRender(<LanguageProvider>{ui}</LanguageProvider>);
}

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1,
    ticker: 'AAA',
    name: 'Alpha Co',
    index_tier: 'NIFTY50',
    direction: 'bullish',
    magnitude_low: 1,
    magnitude_high: 2,
    rationale: 'because it matters here',
    key_points: [],
    confidence_score: 50,
    time_horizon: 'Short-Term',
    basis: 'direct_mention',
    confidence: 'llm_estimate',
    market: 'IN',
    in_my_holdings: false,
    past_mentions: [],
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

  it('expands a ReasoningPanel when a company is tapped', async () => {
    render(<TierRows companies={[company({ company_id: 1, rationale: 'Resilient earnings growth expected here.' })]} />);
    await userEvent.click(screen.getByText('AAA'));
    expect(screen.getByText(/Resilient earnings growth/)).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<TierRows companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
