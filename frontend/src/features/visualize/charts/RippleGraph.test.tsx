import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import RippleGraph from './RippleGraph';
import type { AlertCompany, ImpactGraph } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

function render(graph: ImpactGraph, companies: AlertCompany[] = [], eventType?: string | null) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>
        <RippleGraph graph={graph} companies={companies} eventType={eventType} />
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

const graph: ImpactGraph = {
  nodes: [
    { id: 'news', kind: 'news', label: 'Repo rate cut' },
    { id: 'sector:banking', kind: 'sector', label: 'banking' },
    { id: 'company:1', kind: 'company', company_id: 1, ticker: 'HDFCBANK.NS', label: 'HDFC Bank', name: 'HDFC Bank', direction: 'bullish', confidence_score: 80, impact_level: 'direct' },
  ],
  edges: [
    { from: 'news', to: 'sector:banking', relation: 'correlation', direction: 'bullish', note: 'n0', source: 'llm_only' },
    { from: 'sector:banking', to: 'company:1', relation: 'demand', direction: 'bullish', note: 'n1', source: 'rulebook_pruned' },
  ],
  gaps: [],
};

describe('RippleGraph', () => {
  it('renders wrapped in ChartCardShell with number 2', () => {
    render(graph);
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('Ripple Effect Graph')).toBeInTheDocument();
  });

  it('renders nothing for a graph with only the news node', () => {
    const { container } = render({ nodes: [{ id: 'news', kind: 'news', label: 'x' }], edges: [], gaps: [] });
    expect(container).toBeEmptyDOMElement();
  });

  it('shows a toggle for pruned edges only when at least one exists', () => {
    render(graph);
    expect(screen.getByText(/pruned edges/i)).toBeInTheDocument();
  });

  it('does not show a pruned-edge toggle when there are none', () => {
    const noPruned: ImpactGraph = {
      ...graph,
      edges: graph.edges.map((e) => ({ ...e, source: 'llm_only' })),
    };
    render(noPruned);
    expect(screen.queryByText(/pruned edges/i)).not.toBeInTheDocument();
  });

  it('opens the ReasoningPanel when a company node is tapped', async () => {
    render(graph, [alertCompany({ company_id: 1, rationale: 'Lower rates lift loan demand.' })]);
    await userEvent.click(screen.getByText('HDFCBANK.NS'));
    expect(screen.getByText(/Lower rates lift loan demand/)).toBeInTheDocument();
  });
});
