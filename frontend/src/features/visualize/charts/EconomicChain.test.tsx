import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import EconomicChain, { reachableCompanyIds } from './EconomicChain';
import type { AlertArticle, AlertCompany, ImpactGraph } from '../../../lib/api';

const article: AlertArticle = { id: 1, title: 'RBI increases repo rate by 25 bps to 6.75%', url: 'https://example.com', image_url: null };
const alertCreatedAt = '2026-07-20T10:30:00Z';

function alertCompany(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention',
    confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

const chainGraph: ImpactGraph = {
  nodes: [
    { id: 'news', kind: 'news', label: 'x' },
    { id: 'mech:a', kind: 'mechanism', label: 'Repo Rate ↓' },
    { id: 'mech:b', kind: 'mechanism', label: 'Borrowing Costs ↓' },
    { id: 'sector:banking', kind: 'sector', label: 'banking' },
    { id: 'company:1', kind: 'company', company_id: 1, ticker: 'HDFCBANK.NS', label: 'HDFC Bank', name: 'HDFC Bank', direction: 'bullish', confidence_score: 80 },
  ],
  edges: [
    { from: 'news', to: 'mech:a', relation: 'correlation', direction: 'bullish', note: 'n', source: 'llm_only' },
    { from: 'mech:a', to: 'mech:b', relation: 'credit_cost', direction: 'bullish', note: 'n', source: 'rulebook_verified' },
    { from: 'mech:b', to: 'sector:banking', relation: 'credit_cost', direction: 'bullish', note: 'n', source: 'rulebook_verified' },
    { from: 'sector:banking', to: 'company:1', relation: 'demand', direction: 'bullish', note: 'n', source: 'llm_only' },
  ],
  gaps: [],
};

describe('EconomicChain', () => {
  it('renders wrapped in ChartCardShell with number 9', () => {
    render(<EconomicChain graph={chainGraph} companies={[]} article={article} alertCreatedAt={alertCreatedAt} />);
    expect(screen.getByText('9')).toBeInTheDocument();
    expect(screen.getByText('Economic Chain')).toBeInTheDocument();
  });

  it('renders every mechanism-kind node vertically', () => {
    render(<EconomicChain graph={chainGraph} companies={[]} article={article} alertCreatedAt={alertCreatedAt} />);
    expect(screen.getByText('Repo Rate ↓')).toBeInTheDocument();
    expect(screen.getByText('Borrowing Costs ↓')).toBeInTheDocument();
  });

  it('never renders sector/company/news nodes', () => {
    render(<EconomicChain graph={chainGraph} companies={[]} article={article} alertCreatedAt={alertCreatedAt} />);
    expect(screen.queryByText('Banking')).not.toBeInTheDocument();
    expect(screen.queryByText('HDFCBANK.NS')).not.toBeInTheDocument();
  });

  it('labels a mechanism node with the time horizon of the companies it reaches', () => {
    render(
      <EconomicChain
        graph={chainGraph}
        companies={[alertCompany({ company_id: 1, time_horizon: 'Medium-Term' })]}
        article={article}
        alertCreatedAt={alertCreatedAt}
      />,
    );
    expect(screen.getAllByText('Medium-Term').length).toBeGreaterThan(0);
  });

  // This event type genuinely has no rulebook chain (backend
  // app.reasoning.rulebook.CHAINS only covers 5 event types by design --
  // confirmed while diagnosing this chart per
  // CLAUDE_TASK_charts_design_fidelity.md's Phase 5 instructions). The
  // chart must never silently disappear -- it stays mounted with an
  // honest note explaining why there's no chain to show.
  it('shows an honest empty-state note, not nothing, when the graph has no mechanism nodes', () => {
    render(
      <EconomicChain
        graph={{ nodes: [{ id: 'news', kind: 'news', label: 'x' }], edges: [], gaps: [] }}
        companies={[]}
        article={article}
        alertCreatedAt={alertCreatedAt}
      />,
    );
    expect(screen.getByText('9')).toBeInTheDocument();
    expect(screen.getByText('No mechanism chain modeled for this event type yet')).toBeInTheDocument();
  });
});

describe('reachableCompanyIds', () => {
  it('returns every company id reachable via any forward path from a node', () => {
    expect(reachableCompanyIds(chainGraph, 'mech:a')).toEqual(new Set([1]));
  });

  it('returns an empty set for a node with no downstream companies', () => {
    expect(reachableCompanyIds(chainGraph, 'company:1')).toEqual(new Set());
  });
});
