import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import SplitTree from './SplitTree';
import type { AlertCompany } from '../../../lib/api';
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

describe('SplitTree', () => {
  it('shows a Bullish and a Bearish branch with the right counts', () => {
    render(
      <SplitTree
        companies={[
          company({ company_id: 1, direction: 'bullish' }),
          company({ company_id: 2, direction: 'bullish', ticker: 'BBB' }),
          company({ company_id: 3, direction: 'bearish', ticker: 'CCC' }),
        ]}
      />,
    );
    expect(screen.getByText('2 Bullish')).toBeInTheDocument();
    expect(screen.getByText('1 Bearish')).toBeInTheDocument();
  });

  it('ranks companies within each branch by magnitude descending', () => {
    render(
      <SplitTree
        companies={[
          company({ company_id: 1, ticker: 'WEAK_BULL', direction: 'bullish', magnitude_low: 1, magnitude_high: 2 }),
          company({ company_id: 2, ticker: 'STRONG_BULL', direction: 'bullish', magnitude_low: 20, magnitude_high: 30 }),
        ]}
      />,
    );
    const items = screen.getAllByRole('button').map((el) => el.textContent || '');
    const strongIdx = items.findIndex((t) => t.includes('STRONG_BULL'));
    const weakIdx = items.findIndex((t) => t.includes('WEAK_BULL'));
    expect(strongIdx).toBeLessThan(weakIdx);
  });

  it('collapses a branch on tap, hiding its companies', async () => {
    render(<SplitTree companies={[company({ company_id: 1, direction: 'bullish' })]} />);
    expect(screen.getByText('AAA')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Bullish/ }));
    expect(screen.queryByText('AAA')).not.toBeInTheDocument();
  });

  it('expands a ReasoningPanel when a company is tapped', async () => {
    render(<SplitTree companies={[company({ company_id: 1, rationale: 'Refiner margins widen on lower crude.' })]} />);
    await userEvent.click(screen.getByText('AAA'));
    expect(screen.getByText(/Refiner margins widen/)).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<SplitTree companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
