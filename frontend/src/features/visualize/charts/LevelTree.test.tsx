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

  it('shows every company flat within its level, with no parent-company grouping label', () => {
    render(
      <LevelTree
        companies={[
          company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct' }),
          company({ company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1 }),
          company({ company_id: 3, ticker: 'QCOM', name: 'Qualcomm', impact_level: 'indirect_l1', parent_company_id: 1 }),
        ]}
      />,
    );
    expect(screen.getAllByText('Indirect Impact — Level 1')).toHaveLength(2);
    expect(screen.getByText('TSM')).toBeInTheDocument();
    expect(screen.getByText('QCOM')).toBeInTheDocument();
    expect(screen.queryByText(/via/i)).not.toBeInTheDocument();
  });

  it('shows indirect_l2 companies under their own level, flat like every other level', () => {
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
    expect(screen.getByText('ASML.NS')).toBeInTheDocument();
  });

  it('renders wrapped in ChartCardShell with the Cascade Levels title and number 2', () => {
    render(<LevelTree companies={[company({ company_id: 1, ticker: 'NVDA' })]} />);
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('Cascade Levels')).toBeInTheDocument();
  });

  it('shows no full rationale text anywhere, before or after clicking a card', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
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
    await userEvent.click(screen.getByText('TSM'));
    expect(screen.queryByText('Full paragraph rationale text.')).not.toBeInTheDocument();
    expect(screen.getByText('TSMC makes Nvidia chips; fewer orders means less revenue.')).toBeInTheDocument();
  });

  it('reveals which parent a cascade company is linked via, only after clicking it', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    render(
      <LevelTree
        companies={[
          company({ company_id: 1, ticker: 'NVDA', name: 'Nvidia', impact_level: 'direct' }),
          company({
            company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1,
            key_points: ['Fabs Nvidia chips.'],
          }),
        ]}
      />,
    );
    expect(screen.queryByText(/Linked via NVDA/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByText('TSM'));
    expect(screen.getByText(/Linked via NVDA · Nvidia/)).toBeInTheDocument();

    await userEvent.click(screen.getByText('TSM'));
    expect(screen.queryByText(/Linked via NVDA/)).not.toBeInTheDocument();
  });

  it('does not make a direct-level card clickable', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    render(
      <LevelTree
        companies={[company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct', key_points: ['Some point.'] })]}
      />,
    );
    await userEvent.click(screen.getByText('NVDA'));
    expect(screen.queryByText('Some point.')).not.toBeInTheDocument();
  });

  it('shows a sector chip on every company card, including cascade companies', () => {
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
});
