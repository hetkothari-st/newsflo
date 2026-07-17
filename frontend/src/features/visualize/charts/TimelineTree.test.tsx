import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import TimelineTree from './TimelineTree';
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

describe('TimelineTree', () => {
  it('renders wrapped in ChartCardShell with number 7 and title Timeline Tree', () => {
    render(<TimelineTree companies={[company({})]} />);
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText('Timeline Tree')).toBeInTheDocument();
  });

  it('renders one stage per horizon present, in fixed chronological order', () => {
    render(
      <TimelineTree
        companies={[
          company({ company_id: 1, ticker: 'LONG', time_horizon: 'Long-Term' }),
          company({ company_id: 2, ticker: 'NOW', time_horizon: 'Immediate' }),
        ]}
      />,
    );
    const labels = screen.getAllByText(/Immediate|Long-Term/).map((el) => el.textContent || '');
    const immediateIdx = labels.findIndex((t) => t.includes('Immediate'));
    const longIdx = labels.findIndex((t) => t.includes('Long-Term'));
    expect(immediateIdx).toBeGreaterThanOrEqual(0);
    expect(longIdx).toBeGreaterThan(immediateIdx);
    expect(screen.getByText('LONG')).toBeInTheDocument();
    expect(screen.getByText('NOW')).toBeInTheDocument();
  });

  it('expands a ReasoningPanel when a company is tapped', async () => {
    render(<TimelineTree companies={[company({ company_id: 1, rationale: 'Refiner margins widen on lower crude.' })]} />);
    await userEvent.click(screen.getByText('AAA'));
    expect(screen.getByText(/Refiner margins widen/)).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<TimelineTree companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
