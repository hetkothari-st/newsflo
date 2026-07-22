import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import SplitTree from './SplitTree';
import type { AlertArticle, AlertCompany } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

const article: AlertArticle = { id: 1, title: 'Government announces subsidies for EV manufacturing', url: 'https://example.com', image_url: null };
const alertCreatedAt = '2026-07-20T10:30:00Z';

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

describe('SplitTree', () => {
  it('renders wrapped in ChartCardShell with number 6 and title Positive / Negative Split', () => {
    render(<SplitTree companies={[company({})]} article={article} alertCreatedAt={alertCreatedAt} />);
    expect(screen.getByText('6')).toBeInTheDocument();
    expect(screen.getByText('Positive / Negative Split')).toBeInTheDocument();
  });

  it('shows a Positive Impact and a Negative Impact column with the right counts', () => {
    render(
      <SplitTree
        companies={[
          company({ company_id: 1, direction: 'bullish' }),
          company({ company_id: 2, direction: 'bullish', ticker: 'BBB' }),
          company({ company_id: 3, direction: 'bearish', ticker: 'CCC' }),
        ]}
        article={article}
        alertCreatedAt={alertCreatedAt}
      />,
    );
    // "Positive Impact" and "Negative Impact" appear twice (column header + legend), so use getAllByText
    expect(screen.getAllByText('Positive Impact')).toHaveLength(2);
    expect(screen.getAllByText('Negative Impact')).toHaveLength(2);
    expect(screen.getByText('AAA')).toBeInTheDocument();
    expect(screen.getByText('BBB')).toBeInTheDocument();
    expect(screen.getByText('CCC')).toBeInTheDocument();
  });

  // Sparse Data Rule (see CLAUDE_TASK_charts_design_fidelity.md): "Panel
  // charts still show both panels even if one is empty" -- a column
  // silently disappearing when one side has zero companies looks broken,
  // not deliberate. Both panels always render; the empty one shows a
  // quiet "--" instead of a company list.
  it('still renders the Negative Impact column, with an honest empty state, when every company is bullish', () => {
    render(<SplitTree companies={[company({ company_id: 1, direction: 'bullish' })]} article={article} alertCreatedAt={alertCreatedAt} />);
    expect(screen.getAllByText('Positive Impact')).toHaveLength(2);
    expect(screen.getAllByText('Negative Impact')).toHaveLength(2);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('ranks companies within each column by magnitude descending', () => {
    render(
      <SplitTree
        companies={[
          company({ company_id: 1, ticker: 'WEAK_BULL', direction: 'bullish', magnitude_low: 1, magnitude_high: 2 }),
          company({ company_id: 2, ticker: 'STRONG_BULL', direction: 'bullish', magnitude_low: 20, magnitude_high: 30 }),
        ]}
        article={article}
        alertCreatedAt={alertCreatedAt}
      />,
    );
    const items = screen.getAllByRole('button').map((el) => el.textContent || '');
    const strongIdx = items.findIndex((t) => t.includes('STRONG_BULL'));
    const weakIdx = items.findIndex((t) => t.includes('WEAK_BULL'));
    expect(strongIdx).toBeLessThan(weakIdx);
  });

  it('expands a ReasoningPanel when a company is tapped', async () => {
    render(<SplitTree companies={[company({ company_id: 1, rationale: 'Refiner margins widen on lower crude.' })]} article={article} alertCreatedAt={alertCreatedAt} />);
    await userEvent.click(screen.getByText('AAA'));
    expect(screen.getByText(/Refiner margins widen/)).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<SplitTree companies={[]} article={article} alertCreatedAt={alertCreatedAt} />);
    expect(container).toBeEmptyDOMElement();
  });
});
