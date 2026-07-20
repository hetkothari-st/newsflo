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
    // ChartCardShell's legend statically lists all three level labels regardless
    // of which levels have data, so "Direct Impact" (section header + legend
    // entry) appears twice while an absent level's label appears once (legend only).
    expect(screen.getAllByText('Direct Impact')).toHaveLength(2);
    expect(screen.getAllByText('Indirect Impact — Level 1')).toHaveLength(1);
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
    expect(screen.getAllByText('Direct Impact')).toHaveLength(2);
    expect(screen.getAllByText('Indirect Impact — Level 1')).toHaveLength(2);
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
    expect(screen.getAllByText('Indirect Impact — Level 2')).toHaveLength(2);
    expect(screen.getByText(/via TSMC \(TSM\)/i)).toBeInTheDocument();
    expect(screen.getByText('ASML.NS')).toBeInTheDocument();
  });

  it('renders wrapped in ChartCardShell with the Cascade Levels title and number 2', () => {
    render(<LevelTree companies={[company({ company_id: 1, ticker: 'NVDA' })]} />);
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('Cascade Levels')).toBeInTheDocument();
  });

  it('shows no full rationale text anywhere, only key_points behind a Why linked? disclosure', () => {
    render(
      <LevelTree
        companies={[
          company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct', rationale: 'Full paragraph rationale text.' }),
          company({
            company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1,
            rationale: 'Full paragraph rationale text.', key_points: ['TSMC makes Nvidia chips; fewer orders means less revenue.'],
          }),
        ]}
      />,
    );
    expect(screen.queryByText('Full paragraph rationale text.')).not.toBeInTheDocument();
    expect(screen.queryByText('TSMC makes Nvidia chips; fewer orders means less revenue.')).not.toBeInTheDocument();
    expect(screen.getByText('Why linked?')).toBeInTheDocument();
  });

  it('reveals a cascade group key_point only after clicking Why linked?', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    render(
      <LevelTree
        companies={[
          company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct' }),
          company({
            company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1,
            key_points: ['TSMC makes Nvidia chips; fewer orders means less revenue.'],
          }),
        ]}
      />,
    );
    expect(screen.queryByText('TSMC makes Nvidia chips; fewer orders means less revenue.')).not.toBeInTheDocument();
    await userEvent.click(screen.getByText('Why linked?'));
    expect(screen.getByText('TSMC makes Nvidia chips; fewer orders means less revenue.')).toBeInTheDocument();
  });

  it('does not show a Why linked? disclosure on a direct-level card', () => {
    render(
      <LevelTree
        companies={[company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct', key_points: ['Some point.'] })]}
      />,
    );
    expect(screen.queryByText('Why linked?')).not.toBeInTheDocument();
  });

  it('shows a sector chip on every company row, including cascade companies', () => {
    render(
      <LevelTree
        companies={[
          company({ company_id: 1, ticker: 'NVDA', sector: 'it', impact_level: 'direct' }),
          company({ company_id: 2, ticker: 'TSM', name: 'TSMC', sector: 'metals', impact_level: 'indirect_l1', parent_company_id: 1 }),
        ]}
      />,
    );
    expect(screen.getAllByText('IT').length).toBeGreaterThan(0);
    expect(screen.getByText('Metals')).toBeInTheDocument();
  });

  it('forceCollapse with mode collapse hides every card, mode expand shows them again', () => {
    const companies = [
      company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct' }),
      company({ company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1 }),
    ];
    const { rerender } = render(<LevelTree companies={companies} />);
    expect(screen.getByText('NVDA')).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <LanguageProvider>
          <LevelTree companies={companies} forceCollapse={{ mode: 'collapse', version: 1 }} />
        </LanguageProvider>
      </MemoryRouter>,
    );
    expect(screen.queryByText('NVDA')).not.toBeInTheDocument();
    expect(screen.queryByText('TSM')).not.toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <LanguageProvider>
          <LevelTree companies={companies} forceCollapse={{ mode: 'expand', version: 2 }} />
        </LanguageProvider>
      </MemoryRouter>,
    );
    expect(screen.getByText('NVDA')).toBeInTheDocument();
    expect(screen.getByText('TSM')).toBeInTheDocument();
  });
});
