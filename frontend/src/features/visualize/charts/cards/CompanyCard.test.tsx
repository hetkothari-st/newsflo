import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CompanyCard from './CompanyCard';
import type { AlertCompany } from '../../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention',
    confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('CompanyCard portfolio ring', () => {
  it('shows the portfolio ring when the company is held', () => {
    render(<CompanyCard company={company({ in_my_holdings: true })} />);
    expect(screen.getByText('AAA').closest('div')).toHaveClass('ring-2', 'ring-accent-secondary');
  });

  it('shows no ring when the company is not held', () => {
    render(<CompanyCard company={company({ in_my_holdings: false })} />);
    expect(screen.getByText('AAA').closest('div')).not.toHaveClass('ring-2');
  });
});
