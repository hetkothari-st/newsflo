import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SentimentBar from './SentimentBar';
import type { AlertCompany } from '../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('SentimentBar', () => {
  it('shows direct-labeled bullish and bearish counts', () => {
    render(
      <SentimentBar
        companies={[
          company({ company_id: 1, direction: 'bullish' }),
          company({ company_id: 2, direction: 'bullish' }),
          company({ company_id: 3, direction: 'bearish' }),
        ]}
      />,
    );
    expect(screen.getByText('2 Bullish')).toBeInTheDocument();
    expect(screen.getByText('1 Bearish')).toBeInTheDocument();
  });

  it('excludes companies with an unrecognized direction from the counts', () => {
    render(
      <SentimentBar
        companies={[
          company({ company_id: 1, direction: 'bullish' }),
          company({ company_id: 2, direction: 'unknown' }),
        ]}
      />,
    );
    expect(screen.getByText('1 Bullish')).toBeInTheDocument();
    expect(screen.getByText('0 Bearish')).toBeInTheDocument();
  });

  it('renders nothing when there are no companies with a recognized direction', () => {
    const { container } = render(
      <SentimentBar companies={[company({ direction: 'unknown' })]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<SentimentBar companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
