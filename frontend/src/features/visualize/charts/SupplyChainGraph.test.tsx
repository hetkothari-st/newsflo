import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import SupplyChainGraph, { edgeBetween } from './SupplyChainGraph';
import type { AlertArticle, AlertCompany, ImpactGraph } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

const article: AlertArticle = { id: 1, title: 'Repo rate cut announced', url: 'https://example.com', image_url: null };
const alertCreatedAt = '2026-07-20T10:30:00Z';

function render(graph: ImpactGraph, companies: AlertCompany[] = [], eventType?: string | null) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>
        <SupplyChainGraph graph={graph} companies={companies} article={article} alertCreatedAt={alertCreatedAt} eventType={eventType} />
      </LanguageProvider>
    </MemoryRouter>,
  );
}

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
    { id: 'news', kind: 'news', label: 'Repo rate cut announced' },
    { id: 'mech:repo_rate_down', kind: 'mechanism', label: 'Repo Rate ↓' },
    { id: 'sector:banking', kind: 'sector', label: 'banking' },
    { id: 'company:1', kind: 'company', label: 'HDFC Bank', company_id: 1, ticker: 'HDFCBANK.NS', name: 'HDFC Bank', direction: 'bullish', confidence_score: 80 },
  ],
  edges: [
    { from: 'news', to: 'mech:repo_rate_down', relation: 'correlation', direction: 'bullish', note: 'n0', source: 'llm_only' },
    { from: 'mech:repo_rate_down', to: 'sector:banking', relation: 'credit_cost', direction: 'bullish', note: 'n1', source: 'rulebook_verified' },
    { from: 'sector:banking', to: 'company:1', relation: 'demand', direction: 'bullish', note: 'n2', source: 'llm_only' },
  ],
  gaps: [],
};

describe('SupplyChainGraph', () => {
  it('renders wrapped in ChartCardShell with number 3', () => {
    render(chainGraph);
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('Supply Chain Graph')).toBeInTheDocument();
  });

  it('renders the direct company column always, and shows a quiet -- for upstream/downstream with no supplier/customer edges', () => {
    render(chainGraph);
    expect(screen.getByText('HDFC Bank')).toBeInTheDocument();
    expect(screen.getByText('HDFCBANK.NS')).toBeInTheDocument();
    // No real supplier/customer edges in this fixture -- both side columns
    // stay visible with an honest empty placeholder (Sparse Data Rule).
    expect(screen.getAllByText('—')).toHaveLength(2);
  });

  it('populates the Upstream column from a real supplier edge into the direct company', () => {
    const graphWithSupplier: ImpactGraph = {
      nodes: [...chainGraph.nodes, { id: 'company:2', kind: 'company', label: 'Supplier Co', company_id: 2, ticker: 'SUP', name: 'Supplier Co' }],
      edges: [...chainGraph.edges, { from: 'company:2', to: 'company:1', relation: 'supplier', direction: 'bullish', note: 'n3', source: 'llm_only' }],
      gaps: [],
    };
    render(graphWithSupplier);
    expect(screen.getByText('Supplier Co')).toBeInTheDocument();
    expect(screen.getByText('SUP')).toBeInTheDocument();
  });

  it('renders nothing when the graph has no company node at all', () => {
    const { container } = render({ nodes: [{ id: 'news', kind: 'news', label: 'x' }], edges: [], gaps: [] });
    expect(container).toBeEmptyDOMElement();
  });

  it('opens the ReasoningPanel when the direct company node is tapped', async () => {
    render(chainGraph, [alertCompany({ company_id: 1, rationale: 'Lower rates lift loan demand.' })]);
    await userEvent.click(screen.getByText('HDFCBANK.NS'));
    expect(screen.getByText(/Lower rates lift loan demand/)).toBeInTheDocument();
  });
});

describe('edgeBetween', () => {
  it('finds the edge connecting two given node ids', () => {
    const edge = edgeBetween(chainGraph, 'mech:repo_rate_down', 'sector:banking');
    expect(edge?.relation).toBe('credit_cost');
  });

  it('returns undefined when no edge connects the two ids', () => {
    expect(edgeBetween(chainGraph, 'news', 'company:1')).toBeUndefined();
  });
});
