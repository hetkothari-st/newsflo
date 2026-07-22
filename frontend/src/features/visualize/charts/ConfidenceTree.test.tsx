import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import ConfidenceTree from './ConfidenceTree';
import type { AlertArticle, AlertCompany } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

function render(ui: ReactElement) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>{ui}</LanguageProvider>
    </MemoryRouter>,
  );
}

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', confidence_score: 50,
    time_horizon: 'Short-Term', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

const article: AlertArticle = { id: 1, title: 'OPEC+ announces extended oil production cuts', url: 'https://example.com', image_url: null };
const alertCreatedAt = '2026-07-20T10:30:00Z';

describe('ConfidenceTree', () => {
  it('lists every company with a labeled Confidence: N% line, separate from the magnitude line', () => {
    render(
      <ConfidenceTree
        companies={[
          company({ company_id: 1, ticker: 'NVDA', confidence_score: 98 }),
          company({ company_id: 2, ticker: 'AMD', confidence_score: 91 }),
        ]}
        article={article}
        alertCreatedAt={alertCreatedAt}
      />,
    );
    expect(screen.getByText('Confidence: 98%')).toBeInTheDocument();
    expect(screen.getByText('Confidence: 91%')).toBeInTheDocument();
  });

  it('orders companies by confidence_score descending', () => {
    render(
      <ConfidenceTree
        companies={[
          company({ company_id: 1, ticker: 'LOW', confidence_score: 42 }),
          company({ company_id: 2, ticker: 'HIGH', confidence_score: 96 }),
        ]}
        article={article}
        alertCreatedAt={alertCreatedAt}
      />,
    );
    const items = screen.getAllByRole('button').map((el) => el.textContent || '');
    expect(items.findIndex((t) => t.includes('HIGH'))).toBeLessThan(items.findIndex((t) => t.includes('LOW')));
  });

  it('expands a ReasoningPanel when a company is tapped', async () => {
    render(
      <ConfidenceTree
        companies={[company({ company_id: 1, rationale: 'Refiner margins widen on lower crude.' })]}
        article={article}
        alertCreatedAt={alertCreatedAt}
      />,
    );
    await userEvent.click(screen.getByText('AAA'));
    expect(screen.getByText(/Refiner margins widen/)).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<ConfidenceTree companies={[]} article={article} alertCreatedAt={alertCreatedAt} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('groups companies into confidence-band branches, highest band first', () => {
    const { container } = render(
      <ConfidenceTree
        companies={[
          company({ company_id: 1, ticker: 'LOWCO', confidence_score: 20 }), // LOW
          company({ company_id: 2, ticker: 'HICO', confidence_score: 95 }), // VERY_HIGH
        ]}
        article={article}
        alertCreatedAt={alertCreatedAt}
      />,
    );
    // Band name appears more than once by design -- once in the legend,
    // once as the axis entry, once as each present band's own LevelBand.
    expect(screen.getAllByText('Very High').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Low').length).toBeGreaterThan(0);
    const html = container.textContent ?? '';
    expect(html.indexOf('HICO')).toBeGreaterThan(-1);
    expect(html.indexOf('HICO')).toBeLessThan(html.indexOf('LOWCO'));
  });

  it('omits a band branch entirely when no company falls in it', () => {
    render(
      <ConfidenceTree
        companies={[company({ company_id: 1, confidence_score: 50 })]} // MODERATE only
        article={article}
        alertCreatedAt={alertCreatedAt}
      />,
    );
    expect(screen.getAllByText('Moderate').length).toBeGreaterThan(0);
    // The right-side axis always shows every band regardless of data (the
    // scale itself must never look sparse), so "Very High"/"Low" text still
    // exists there -- what's actually omitted is any LevelBand *section*
    // (and therefore any company row) for a band with no companies in it.
    // With one MODERATE company, exactly one company button should exist.
    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  it('renders wrapped in ChartCardShell with number 5 and title Confidence Tree', () => {
    render(<ConfidenceTree companies={[company({})]} article={article} alertCreatedAt={alertCreatedAt} />);
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('Confidence Tree')).toBeInTheDocument();
  });
});
