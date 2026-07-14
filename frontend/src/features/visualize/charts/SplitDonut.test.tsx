import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import SplitDonut from './SplitDonut';
import type { AlertCompany } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

function render(ui: ReactElement) {
  return rtlRender(<LanguageProvider>{ui}</LanguageProvider>);
}

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('SplitDonut', () => {
  it('shows the bullish/bearish count split', () => {
    render(
      <SplitDonut
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

  it('lists companies ranked, bullish first then bearish', () => {
    render(
      <SplitDonut
        companies={[
          company({ company_id: 1, ticker: 'WEAK_BULL', direction: 'bullish', magnitude_low: 1, magnitude_high: 2 }),
          company({ company_id: 2, ticker: 'STRONG_BEAR', direction: 'bearish', magnitude_low: 20, magnitude_high: 30 }),
        ]}
      />,
    );
    const items = screen.getAllByRole('button').map((el) => el.textContent || '');
    const bullishIdx = items.findIndex((item) => item.includes('WEAK_BULL'));
    const bearishIdx = items.findIndex((item) => item.includes('STRONG_BEAR'));
    expect(bullishIdx).toBeLessThan(bearishIdx);
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<SplitDonut companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('expands a ReasoningPanel when a company row is clicked', async () => {
    render(
      <SplitDonut
        companies={[
          company({ company_id: 1, ticker: 'TEST_CO', rationale: 'Strategic acquisition opportunity looming' }),
        ]}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /TEST_CO/ }));
    expect(screen.getByText(/Strategic acquisition opportunity/)).toBeInTheDocument();
  });
});
