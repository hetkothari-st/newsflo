import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import CollapsibleInsightRow from './CollapsibleInsightRow';
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
  key_points: [],
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

describe('CollapsibleInsightRow', () => {
  it('shows only the name and ticker when collapsed, no insight text', () => {
    render(<CollapsibleInsightRow company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" />);
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
    expect(screen.queryByText(/Refiner margins expand/)).not.toBeInTheDocument();
  });

  it('expands to the full InsightCard on click', async () => {
    render(<CollapsibleInsightRow company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" />);
    await userEvent.click(screen.getByText('Reliance Industries'));
    expect(
      screen.getByText((_, el) => el?.tagName === 'SPAN' && /Refiner margins expand/.test(el.textContent ?? '')),
    ).toBeInTheDocument();
  });

  it('collapses back to the name-only row when clicked again', async () => {
    render(<CollapsibleInsightRow company={company} eventType="crude_oil" alertCreatedAt="2026-07-17T10:00:00.000Z" />);
    await userEvent.click(screen.getByRole('button', { name: /Reliance Industries/ }));
    await userEvent.click(screen.getByRole('button', { name: /Reliance Industries/ }));
    expect(
      screen.queryByText((_, el) => el?.tagName === 'SPAN' && /Refiner margins expand/.test(el.textContent ?? '')),
    ).not.toBeInTheDocument();
  });

  it('shows a bearish arrow for a bearish company while collapsed', () => {
    render(
      <CollapsibleInsightRow
        company={{ ...company, direction: 'bearish' }}
        eventType="crude_oil"
        alertCreatedAt="2026-07-17T10:00:00.000Z"
      />,
    );
    expect(screen.getByText('▼')).toBeInTheDocument();
  });
});
