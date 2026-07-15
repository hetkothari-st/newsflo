import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import ConfidenceTree from './ConfidenceTree';
import type { AlertCompany } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';
import { confidenceColor } from '../colors';

function render(ui: ReactElement) {
  return rtlRender(<LanguageProvider>{ui}</LanguageProvider>);
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

describe('ConfidenceTree', () => {
  it('lists every company with its confidence_score as a percentage badge', () => {
    render(
      <ConfidenceTree
        companies={[
          company({ company_id: 1, ticker: 'NVDA', confidence_score: 98 }),
          company({ company_id: 2, ticker: 'AMD', confidence_score: 91 }),
        ]}
      />,
    );
    expect(screen.getByText('98%')).toBeInTheDocument();
    expect(screen.getByText('91%')).toBeInTheDocument();
  });

  it('orders companies by confidence_score descending', () => {
    render(
      <ConfidenceTree
        companies={[
          company({ company_id: 1, ticker: 'LOW', confidence_score: 42 }),
          company({ company_id: 2, ticker: 'HIGH', confidence_score: 96 }),
        ]}
      />,
    );
    const items = screen.getAllByRole('button').map((el) => el.textContent || '');
    expect(items.findIndex((t) => t.includes('HIGH'))).toBeLessThan(items.findIndex((t) => t.includes('LOW')));
  });

  it('expands a ReasoningPanel when a company is tapped', async () => {
    render(<ConfidenceTree companies={[company({ company_id: 1, rationale: 'Refiner margins widen on lower crude.' })]} />);
    await userEvent.click(screen.getByText('AAA'));
    expect(screen.getByText(/Refiner margins widen/)).toBeInTheDocument();
  });

  it('colors each badge via the validated confidence ramp', () => {
    render(<ConfidenceTree companies={[company({ company_id: 1, ticker: 'NVDA', confidence_score: 98 })]} />);
    expect(screen.getByText('98%')).toHaveStyle({ color: confidenceColor(98) });
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<ConfidenceTree companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
