import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import LevelTree from './LevelTree';
import type { AlertArticle, AlertCompany } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

const article: AlertArticle = { id: 1, title: 'Chip export restrictions announced', url: 'https://example.com', image_url: null };

function render(companies: AlertCompany[], eventType?: string | null) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>
        <LevelTree companies={companies} article={article} alertCreatedAt="2026-07-20T10:30:00Z" eventType={eventType} />
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
    const { container } = render([]);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders only a Direct Impact branch when every company is direct', () => {
    render([company({ company_id: 1, ticker: 'NVDA' })]);
    expect(screen.getAllByText('Direct Impact')).toHaveLength(2);
    expect(screen.getAllByText('Indirect Impact — Level 1')).toHaveLength(1);
    expect(screen.getByText('NVDA')).toBeInTheDocument();
  });

  it('shows every company flat within its level, with no parent-company grouping label', () => {
    render([
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
    render([
      company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct' }),
      company({ company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1 }),
      company({ company_id: 3, ticker: 'ASML.NS', name: 'ASML Holding', impact_level: 'indirect_l2', parent_company_id: 2 }),
    ]);
    expect(screen.getAllByText('Indirect Impact — Level 2')).toHaveLength(2);
    expect(screen.getByText('ASML.NS')).toBeInTheDocument();
  });

  it('renders wrapped in ChartCardShell with the Cascade Levels title and number 4', () => {
    render([company({ company_id: 1, ticker: 'NVDA' })]);
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('Cascade Levels')).toBeInTheDocument();
  });

  it('shows no full rationale text anywhere until a company is tapped', () => {
    render([
      company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct', rationale: 'Full paragraph rationale text.' }),
      company({
        company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1,
        rationale: 'Full paragraph rationale text.',
      }),
    ]);
    expect(screen.queryByText('Full paragraph rationale text.')).not.toBeInTheDocument();
  });

  it('expands a ReasoningPanel for a direct company on click', async () => {
    render([company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct', rationale: 'Chip demand accelerates.' })]);
    await userEvent.click(screen.getByText('NVDA'));
    expect(screen.getByText(/Chip demand accelerates/)).toBeInTheDocument();
  });

  it('expands a ReasoningPanel for a cascade company on click, using its own company id', async () => {
    render([
      company({ company_id: 1, ticker: 'NVDA', impact_level: 'direct' }),
      company({
        company_id: 2, ticker: 'TSM', name: 'TSMC', impact_level: 'indirect_l1', parent_company_id: 1,
        rationale: 'Foundry capacity is the binding constraint.',
      }),
    ]);
    await userEvent.click(screen.getByText('TSM'));
    expect(screen.getByText(/Foundry capacity is the binding constraint/)).toBeInTheDocument();
  });

  // The design-fidelity rebuild fixed one company-node design across every
  // chart (name, ticker, magnitude -- see CompanyNode) -- a per-chart sector
  // chip is no longer part of it, so this replaces the old sector-chip
  // assertion with a check on the shared design's own magnitude display.
  it('shows the magnitude range, not confidence_score, on every company card', () => {
    render([
      company({ company_id: 1, ticker: 'NVDA', direction: 'bearish', magnitude_low: -23, magnitude_high: -21, confidence_score: 88, impact_level: 'direct' }),
    ]);
    expect(screen.getByText('▼ -23%–-21%')).toBeInTheDocument();
    expect(screen.queryByText(/88/)).not.toBeInTheDocument();
  });
});
