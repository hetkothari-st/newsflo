import { render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import LevelTree from './LevelTree';
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
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50', sector: 'it',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', confidence_score: 50,
    time_horizon: 'Short-Term', market: 'IN', in_my_holdings: false, past_mentions: [],
    impact_level: 'direct', parent_company_id: null,
    ...overrides,
  };
}

describe('LevelTree', () => {
  it('renders nothing for an empty company list', () => {
    const { container } = render(<LevelTree companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders only a Direct Impact branch when every company is direct', () => {
    render(<LevelTree companies={[company({ company_id: 1, ticker: 'NVDA' })]} />);
    expect(screen.getByText('Direct Impact')).toBeInTheDocument();
    expect(screen.queryByText('Indirect Impact — Level 1')).not.toBeInTheDocument();
    expect(screen.getByText('NVDA')).toBeInTheDocument();
  });

  it('groups indirect_l1 companies under a branch labeled with their parent', () => {
    render(
      <LevelTree
        companies={[
          company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct' }),
          company({
            company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1,
          }),
        ]}
      />,
    );
    expect(screen.getByText('Direct Impact')).toBeInTheDocument();
    expect(screen.getByText('Indirect Impact — Level 1')).toBeInTheDocument();
    expect(screen.getByText(/via Alpha Co \(NVDA\)/i)).toBeInTheDocument();
    expect(screen.getByText('TSM')).toBeInTheDocument();
  });

  it('chains indirect_l2 companies under their indirect_l1 parent, not the top-level direct company', () => {
    render(
      <LevelTree
        companies={[
          company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct' }),
          company({ company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1 }),
          company({ company_id: 3, ticker: 'ASML.NS', name: 'ASML Holding', impact_level: 'indirect_l2', parent_company_id: 2 }),
        ]}
      />,
    );
    expect(screen.getByText('Indirect Impact — Level 2')).toBeInTheDocument();
    expect(screen.getByText(/via TSMC \(TSM\)/i)).toBeInTheDocument();
    expect(screen.getByText('ASML.NS')).toBeInTheDocument();
  });

  it('expands a ReasoningPanel when a leaf is tapped', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    render(<LevelTree companies={[company({ company_id: 1, ticker: 'NVDA', rationale: 'Export ban hits Nvidia directly.' })]} />);
    await userEvent.click(screen.getByText('NVDA'));
    expect(screen.getByText(/Export ban hits Nvidia directly/)).toBeInTheDocument();
  });
});
