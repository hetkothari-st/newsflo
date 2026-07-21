import { render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import LevelTree from './LevelTree';
import type { AlertCompany } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

// LevelTree navigates on click (to the full reasoning page), so tests need
// a real Routes tree with a stub destination to observe -- not just a bare
// MemoryRouter -- to prove the right URL was actually navigated to.
function renderAtRoute(companies: AlertCompany[], alertId = 7) {
  return rtlRender(
    <MemoryRouter initialEntries={['/start']}>
      <LanguageProvider>
        <Routes>
          <Route path="/start" element={<LevelTree alertId={alertId} companies={companies} />} />
          <Route
            path="/alerts/:id/company/:companyId"
            element={<p>Reasoning page placeholder</p>}
          />
        </Routes>
      </LanguageProvider>
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
    const { container } = renderAtRoute([]);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders only a Direct Impact branch when every company is direct', () => {
    renderAtRoute([company({ company_id: 1, ticker: 'NVDA' })]);
    // ChartCardShell's legend statically lists all three level labels regardless
    // of which levels have data, so "Direct Impact" (section header + legend
    // entry) appears twice while an absent level's label appears once (legend only).
    expect(screen.getAllByText('Direct Impact')).toHaveLength(2);
    expect(screen.getAllByText('Indirect Impact — Level 1')).toHaveLength(1);
    expect(screen.getByText('NVDA')).toBeInTheDocument();
  });

  it('shows every company flat within its level, with no parent-company grouping label', () => {
    renderAtRoute([
      company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct' }),
      company({ company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1 }),
      company({ company_id: 3, ticker: 'QCOM', name: 'Qualcomm', impact_level: 'indirect_l1', parent_company_id: 1 }),
    ]);
    expect(screen.getAllByText('Indirect Impact — Level 1')).toHaveLength(2);
    expect(screen.getByText('TSM')).toBeInTheDocument();
    expect(screen.getByText('QCOM')).toBeInTheDocument();
    expect(screen.queryByText(/via/i)).not.toBeInTheDocument();
  });

  it('shows indirect_l2 companies under their own level, flat like every other level', () => {
    renderAtRoute([
      company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct' }),
      company({ company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1 }),
      company({ company_id: 3, ticker: 'ASML.NS', name: 'ASML Holding', impact_level: 'indirect_l2', parent_company_id: 2 }),
    ]);
    expect(screen.getAllByText('Indirect Impact — Level 2')).toHaveLength(2);
    expect(screen.getByText('ASML.NS')).toBeInTheDocument();
  });

  it('renders wrapped in ChartCardShell with the Cascade Levels title and number 2', () => {
    renderAtRoute([company({ company_id: 1, ticker: 'NVDA' })]);
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('Cascade Levels')).toBeInTheDocument();
  });

  it('shows no full rationale text anywhere', () => {
    renderAtRoute([
      company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct', rationale: 'Full paragraph rationale text.' }),
      company({
        company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1,
        rationale: 'Full paragraph rationale text.',
      }),
    ]);
    expect(screen.queryByText('Full paragraph rationale text.')).not.toBeInTheDocument();
  });

  it('navigates to the full reasoning page for a direct company on click', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    renderAtRoute([company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct' })], 42);

    await userEvent.click(screen.getByText('NVDA'));

    expect(screen.getByText('Reasoning page placeholder')).toBeInTheDocument();
  });

  it('navigates to the full reasoning page for a cascade company on click, using its own company id', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    renderAtRoute(
      [
        company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct' }),
        company({ company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1 }),
      ],
      42,
    );

    await userEvent.click(screen.getByText('TSM'));

    expect(screen.getByText('Reasoning page placeholder')).toBeInTheDocument();
  });

  it('shows a sector chip on every company card, including cascade companies', () => {
    renderAtRoute([
      company({ company_id: 1, ticker: 'NVDA', sector: 'it', impact_level: 'direct' }),
      company({ company_id: 2, ticker: 'TSM', name: 'TSMC', sector: 'metals', impact_level: 'indirect_l1', parent_company_id: 1 }),
    ]);
    expect(screen.getAllByText('IT').length).toBeGreaterThan(0);
    expect(screen.getByText('Metals')).toBeInTheDocument();
  });
});
