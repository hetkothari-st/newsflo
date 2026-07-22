import { render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import ImpactTree from './ImpactTree';
import type { AlertArticle, AlertCompany, ImpactGraph } from '../../../lib/api';
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
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50', sector: 'oil_gas',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', confidence_score: 50,
    time_horizon: 'Short-Term', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

const article: AlertArticle = { id: 1, title: 'RBI increases repo rate by 25 bps', url: 'https://example.com', image_url: null };
const emptyGraph: ImpactGraph = { nodes: [], edges: [], gaps: [] };

// A real news->sector mechanism edge (backend
// app.analysis.cascade._sector_mechanism_edges) -- the genuine, per-article
// sector-level reasoning, independent of any one company's rationale.
function graphWithSectorMechanism(sector: string, note: string): ImpactGraph {
  return {
    nodes: [{ id: 'news', kind: 'news', label: 'x' }, { id: `sector:${sector}`, kind: 'sector', label: sector }],
    edges: [{ from: 'news', to: `sector:${sector}`, relation: 'correlation', direction: 'bullish', note, source: 'llm_only' }],
    gaps: [],
  };
}

describe('ImpactTree', () => {
  it('renders wrapped in ChartCardShell with number 1 and title Multi-Level Impact Tree', () => {
    render(<ImpactTree companies={[]} graph={emptyGraph} article={article} alertCreatedAt="2026-07-17T10:30:00Z" />);
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('Multi-Level Impact Tree')).toBeInTheDocument();
  });

  it('renders the news article title', () => {
    render(<ImpactTree companies={[]} graph={emptyGraph} article={article} alertCreatedAt="2026-07-17T10:30:00Z" />);
    expect(screen.getByText('RBI increases repo rate by 25 bps')).toBeInTheDocument();
  });

  it('renders a direct-impact sector and its company as Level 1/2', () => {
    render(
      <ImpactTree
        companies={[company({ company_id: 1, impact_level: 'direct', sector: 'banking', ticker: 'HDFCBANK' })]}
        graph={emptyGraph}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('Banking')).toBeInTheDocument();
    expect(screen.getByText('HDFCBANK')).toBeInTheDocument();
  });

  it('renders an indirect company\'s sub-sector and ticker as Level 3/4', () => {
    render(
      <ImpactTree
        companies={[
          company({ company_id: 1, impact_level: 'indirect_l1', sector: 'banking', sub_sector: 'nbfc', ticker: 'BAJFINANCE' }),
        ]}
        graph={emptyGraph}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('NBFC')).toBeInTheDocument();
    expect(screen.getByText('BAJFINANCE')).toBeInTheDocument();
  });

  it('shows an empty note instead of Level 3/4 when there are no indirect companies', () => {
    render(
      <ImpactTree
        companies={[company({ company_id: 1, impact_level: 'direct' })]}
        graph={emptyGraph}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('No indirect ripple effects identified.')).toBeInTheDocument();
  });

  it('shows an empty note instead of Level 1/2 when there are no direct companies', () => {
    render(
      <ImpactTree
        companies={[company({ company_id: 1, impact_level: 'indirect_l1', sub_sector: 'nbfc' })]}
        graph={emptyGraph}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('No direct impact identified.')).toBeInTheDocument();
  });

  // Regression (live user feedback): the WHY block used to show the
  // highest-confidence COMPANY's own rationale, mislabeled as the sector's
  // explanation -- misleading whenever a sector's companies had different
  // individual angles. It now reads the real, dedicated sector-level
  // mechanism edge instead (backend _sector_mechanism_edges), never a
  // company's rationale, whenever that edge exists.
  it('shows the sector\'s own real mechanism text as the WHY explanation, not any company\'s rationale', () => {
    render(
      <ImpactTree
        companies={[
          company({ company_id: 1, impact_level: 'direct', sector: 'banking', confidence_score: 40, rationale: 'Lower rationale.' }),
          company({ company_id: 2, impact_level: 'direct', sector: 'banking', confidence_score: 90, rationale: 'Rate cut directly compresses net interest margins.' }),
        ]}
        graph={graphWithSectorMechanism('banking', 'Rate cuts reduce funding costs economy-wide for lenders.')}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('Rate cuts reduce funding costs economy-wide for lenders.')).toBeInTheDocument();
    expect(screen.queryByText('Rate cut directly compresses net interest margins.')).not.toBeInTheDocument();
    expect(screen.queryByText('Lower rationale.')).not.toBeInTheDocument();
  });

  it('falls back to the top company\'s rationale only when no sector mechanism edge exists', () => {
    render(
      <ImpactTree
        companies={[
          company({ company_id: 1, impact_level: 'direct', sector: 'banking', confidence_score: 90, rationale: 'Rate cut directly compresses net interest margins.' }),
        ]}
        graph={emptyGraph}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('Rate cut directly compresses net interest margins.')).toBeInTheDocument();
  });

  it('shows the sub-sector\'s parent-sector mechanism text as its WHY explanation', () => {
    render(
      <ImpactTree
        companies={[
          company({
            company_id: 1,
            impact_level: 'indirect_l1',
            sector: 'banking',
            sub_sector: 'nbfc',
            confidence_score: 70,
            rationale: 'NBFCs face higher funding costs as rates rise.',
          }),
        ]}
        graph={graphWithSectorMechanism('banking', 'Banking-sector funding cost pressure ripples to adjacent lenders.')}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('Banking-sector funding cost pressure ripples to adjacent lenders.')).toBeInTheDocument();
    expect(screen.queryByText('NBFCs face higher funding costs as rates rise.')).not.toBeInTheDocument();
  });

  it('expands a ReasoningPanel when a direct company is tapped', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    render(
      <ImpactTree
        companies={[company({ company_id: 1, ticker: 'HDFCBANK', sector: 'banking', impact_level: 'direct', rationale: 'Lower rates lift loan demand.' })]}
        graph={graphWithSectorMechanism('banking', 'Rate cuts lower funding costs for banks broadly.')}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    await userEvent.click(screen.getByText('HDFCBANK'));
    expect(screen.getByText(/Lower rates lift loan demand/)).toBeInTheDocument();
  });

  it('expands a ReasoningPanel when an indirect (sub-sector) company is tapped', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    render(
      <ImpactTree
        companies={[company({
          company_id: 1, ticker: 'ULTRACEMCO', sector: 'infra', impact_level: 'indirect_l1',
          parent_company_id: 99, rationale: 'Cement demand rises with construction activity.',
        })]}
        graph={graphWithSectorMechanism('infra', 'Infrastructure spending ripples to construction-input suppliers.')}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    await userEvent.click(screen.getByText('ULTRACEMCO'));
    expect(screen.getByText(/Cement demand rises/)).toBeInTheDocument();
  });
});
