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

  it('shows the why text when present', () => {
    render(
      <InsightCard
        company={{ ...company, why: 'Widening refining margins directly lift Reliance earnings.' }}
        eventType="crude_oil"
        alertCreatedAt="2026-07-17T10:00:00.000Z"
      />,
    );
    expect(screen.getByText('Widening refining margins directly lift Reliance earnings.')).toBeInTheDocument();
  });

  it('renders nothing extra for why when absent', () => {
    render(
      <InsightCard
        company={{ ...company, why: null }}
        eventType="crude_oil"
        alertCreatedAt="2026-07-17T10:00:00.000Z"
      />,
    );
    expect(screen.queryByText(/directly lift Reliance earnings/)).not.toBeInTheDocument();
  });

  it('renders the sourced classification and ratios with an as-of date', () => {
    render(
      <InsightCard
        company={{
          ...company,
          business_desc: null,
          fundamentals: {
            classification: {
              sector: 'Energy',
              industry: 'Oil, Gas & Consumable Fuels',
              group: 'Petroleum Products',
              sub_group: 'Refineries & Marketing',
            },
            ratios: { pe: 44.95, opm: 14.24 },
            source: 'BSE',
            as_of: '2026-08-04',
          },
        }}
        eventType="crude_oil"
        alertCreatedAt="2026-07-17T10:00:00.000Z"
      />,
    );
    expect(screen.getByText(/Refineries & Marketing/)).toBeInTheDocument();
    expect(screen.getByText('44.95')).toBeInTheDocument();
    // The date is load-bearing, not decoration: PE is price-derived and this
    // data refreshes monthly (spec 5.1).
    expect(screen.getByText(/2026-08-04/)).toBeInTheDocument();
  });

  it('renders nothing when fundamentals is null', () => {
    const { container } = render(
      <InsightCard
        company={{ ...company, business_desc: null, fundamentals: null }}
        eventType="crude_oil"
        alertCreatedAt="2026-07-17T10:00:00.000Z"
      />,
    );
    expect(container.querySelector("[data-testid='fundamentals']")).toBeNull();
  });

  it('renders a real zero ratio as 0.00, not omitted', () => {
    render(
      <InsightCard
        company={{
          ...company,
          business_desc: null,
          fundamentals: {
            classification: { sector: 'Energy', industry: null, group: null, sub_group: null },
            ratios: { npm: 0.0 },
            source: 'BSE',
            as_of: '2026-08-04',
          },
        }}
        eventType="crude_oil"
        alertCreatedAt="2026-07-17T10:00:00.000Z"
      />,
    );
    expect(screen.getByText('0.00')).toBeInTheDocument();
  });

  it('hides the logo/name/ticker header block when hideHeader is set, but keeps the price line', () => {
    render(
      <InsightCard
        company={{ ...company, price_at_analysis: 2500, return_1m: 3.2 }}
        eventType="crude_oil"
        alertCreatedAt="2026-07-17T10:00:00.000Z"
        hideHeader
      />,
    );
    expect(screen.queryByText('RELIANCE.NS')).not.toBeInTheDocument();
    expect(screen.getByText('2500.00', { exact: false })).toBeInTheDocument();
  });

  it('shows the logo/name/ticker header block by default (hideHeader unset)', () => {
    render(<InsightCard company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" />);
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
  });

  it('shows "Linked via" the parent company when one is given (why this company is in the Ripple bucket)', () => {
    const parent: AlertCompany = { ...company, company_id: 2, ticker: 'RELIANCE.NS', name: 'Reliance Industries' };
    render(
      <InsightCard
        company={{ ...company, company_id: 3, impact_level: 'indirect_l1', parent_company_id: 2 }}
        eventType="crude_oil"
        alertCreatedAt="2026-07-17T10:00:00.000Z"
        parentCompany={parent}
      />,
    );
    expect(screen.getByText('Linked via RELIANCE.NS · Reliance Industries')).toBeInTheDocument();
  });

  it('renders no "Linked via" line for a direct company (no parent)', () => {
    render(<InsightCard company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" />);
    expect(screen.queryByText(/Linked via/)).not.toBeInTheDocument();
  });

  it('renders no fundamentals panel when the company has no sector and no fundamentals', () => {
    const { container } = render(
      <InsightCard
        company={{ ...company, sector: undefined, business_desc: null }}
        eventType="crude_oil"
        alertCreatedAt="2026-07-17T10:00:00.000Z"
      />,
    );
    expect(container.querySelector("[data-testid='fundamentals']")).toBeNull();
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
