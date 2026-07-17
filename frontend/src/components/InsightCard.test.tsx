import { render as rtlRender, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import InsightCard from './InsightCard';
import type { AlertCompany } from '../lib/api';
import * as api from '../lib/api';
import { LanguageProvider } from '../lib/language';

function render(ui: ReactElement) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>{ui}</LanguageProvider>
    </MemoryRouter>,
  );
}

const company: AlertCompany = {
  company_id: 1,
  ticker: 'RELIANCE.NS',
  name: 'Reliance Industries',
  index_tier: 'NIFTY50',
  direction: 'bullish',
  magnitude_low: 2,
  magnitude_high: 4,
  rationale: 'Refiner margins expand on crude softness.',
  key_points: [
    'Crude softness widens refining margin.',
    'Peer refiners saw similar moves last cycle.',
    'Watch Brent for reversal risk.',
    'Analyst consensus target raised 4% this quarter.',
  ],
  confidence_score: 84,
  time_horizon: 'Short-Term',
  basis: 'direct_mention',
  confidence: 'llm_estimate',
  market: 'IN',
  in_my_holdings: false,
  past_mentions: [],
  impact_level: 'direct',
};

beforeEach(() => {
  vi.spyOn(api, 'getCompanyPrices').mockResolvedValue({ period: '1mo', points: [], available: false });
});

describe('InsightCard', () => {
  it('shows the company name, ticker, and confidence gauge', () => {
    render(<InsightCard company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" />);
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
    expect(screen.getByText('84%')).toBeInTheDocument();
  });

  it('shows the first 3 key points by default, not just 1', () => {
    render(<InsightCard company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" />);
    expect(screen.getByText('Crude softness widens refining margin.')).toBeInTheDocument();
    expect(screen.getByText('Peer refiners saw similar moves last cycle.')).toBeInTheDocument();
    expect(screen.getByText('Watch Brent for reversal risk.')).toBeInTheDocument();
    expect(screen.queryByText('Analyst consensus target raised 4% this quarter.')).not.toBeInTheDocument();
  });

  it('expands remaining key points beyond the first 3 on "see more" and collapses on "see less"', async () => {
    render(<InsightCard company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" />);
    await userEvent.click(screen.getByText('+ 1 more insights'));
    expect(screen.getByText('Analyst consensus target raised 4% this quarter.')).toBeInTheDocument();

    await userEvent.click(screen.getByText('See less'));
    expect(screen.queryByText('Analyst consensus target raised 4% this quarter.')).not.toBeInTheDocument();
  });

  it('does not show the see-more toggle when there are 3 or fewer key points', () => {
    render(
      <InsightCard
        company={{ ...company, key_points: ['Only point.'] }}
        eventType="crude_oil"
        alertCreatedAt="2026-07-17T10:00:00.000Z"
      />,
    );
    expect(screen.queryByText(/more insights/)).not.toBeInTheDocument();
  });

  it('falls back to a truncated rationale when key_points is empty (legacy alert)', () => {
    render(
      <InsightCard
        company={{ ...company, key_points: [] }}
        eventType="crude_oil"
        alertCreatedAt="2026-07-17T10:00:00.000Z"
      />,
    );
    // Plain regex getByText substring-matches every ancestor's full
    // textContent too (RTL matches per-element, not just leaves), which
    // would throw "multiple elements found" here since the point is
    // nested inside several containers -- constrain the match to the leaf
    // <span> the bullet text actually lives in.
    expect(
      screen.getByText((_, el) => el?.tagName === 'SPAN' && /Refiner margins expand/.test(el.textContent ?? '')),
    ).toBeInTheDocument();
  });

  it('links "Read full analysis" to the detail route', () => {
    render(<InsightCard company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" alertId={7} />);
    const link = screen.getByRole('link', { name: /read full analysis/i });
    expect(link).toHaveAttribute('href', '/alerts/7/company/1');
  });

  it('fetches and renders a sparkline when a price series is available', async () => {
    vi.spyOn(api, 'getCompanyPrices').mockResolvedValue({
      period: '1mo',
      points: [{ date: '2026-06-17', close: 100 }, { date: '2026-07-17', close: 110 }],
      available: true,
    });
    const { container } = render(
      <InsightCard company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" />,
    );
    await waitFor(() => expect(container.querySelector('svg')).not.toBeNull());
  });
});
