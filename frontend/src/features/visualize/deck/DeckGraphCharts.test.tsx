import { render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import type { ImpactGraph } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';
import { ThemeProvider } from '../../../lib/theme';
import DeckRipple from './DeckRipple';
import DeckSupplyChain from './DeckSupplyChain';
import DeckEconomicChain from './DeckEconomicChain';
import DeckKnowledge from './DeckKnowledge';
import { company } from './fixtures';

function render(ui: ReactElement) {
  return rtlRender(
    <MemoryRouter>
      <ThemeProvider>
        <LanguageProvider>{ui}</LanguageProvider>
      </ThemeProvider>
    </MemoryRouter>,
  );
}

const companies = [
  company({ company_id: 1, ticker: 'HDFCBANK', name: 'HDFC Bank', impact_level: 'direct', time_horizon: 'Immediate' }),
  company({ company_id: 2, ticker: 'DLF', name: 'DLF', impact_level: 'indirect_l1', parent_company_id: 1, time_horizon: 'Medium-Term' }),
];

const graph: ImpactGraph = {
  nodes: [
    { id: 'news', kind: 'news', label: 'RBI raises repo rate' },
    { id: 'mech:borrowing_costs_up', kind: 'mechanism', label: 'Borrowing Costs ↑' },
    { id: 'sector:banking', kind: 'sector', label: 'banking' },
    { id: 'company:1', kind: 'company', company_id: 1, ticker: 'HDFCBANK', label: 'HDFC Bank', name: 'HDFC Bank', direction: 'bearish', confidence_score: 88, impact_level: 'direct' },
    { id: 'company:2', kind: 'company', company_id: 2, ticker: 'DLF', label: 'DLF', name: 'DLF', direction: 'bearish', confidence_score: 61, impact_level: 'indirect_l1' },
  ],
  edges: [
    { from: 'news', to: 'mech:borrowing_costs_up', relation: 'credit_cost', direction: 'bearish', note: 'n', source: 'rulebook_verified' },
    { from: 'mech:borrowing_costs_up', to: 'sector:banking', relation: 'credit_cost', direction: 'bearish', note: 'n', source: 'rulebook_verified' },
    { from: 'sector:banking', to: 'company:1', relation: 'demand', direction: 'bearish', note: 'n', source: 'llm_only' },
    { from: 'company:1', to: 'company:2', relation: 'customer', direction: 'bearish', note: 'n', source: 'rulebook_pruned' },
  ],
  gaps: [{ sector: 'auto', impact_level: 'indirect_l1', reason: 'resolution failed' }],
};

describe('DeckRipple (chart 2)', () => {
  it('renders the graph with a default-on pruned toggle and a gaps note', () => {
    render(<DeckRipple graph={graph} companies={companies} />);
    expect(screen.getByText('Ripple Effect')).toBeInTheDocument();
    expect(screen.getByText(/Hide 1 pruned/)).toBeInTheDocument();
    expect(screen.getByText(/Unresolved: Auto/)).toBeInTheDocument();
  });

  it('shows an honest empty state instead of rendering nothing', () => {
    render(<DeckRipple graph={{ nodes: [{ id: 'news', kind: 'news', label: 'x' }], edges: [], gaps: [] }} companies={[]} />);
    expect(screen.getByText(/No impact graph resolved/)).toBeInTheDocument();
  });
});

describe('DeckSupplyChain (chart 3)', () => {
  it('always renders all three columns, empty ones as —', () => {
    render(<DeckSupplyChain graph={graph} companies={companies} />);
    expect(screen.getByText('Upstream')).toBeInTheDocument();
    expect(screen.getByText('Direct')).toBeInTheDocument();
    expect(screen.getByText('Downstream')).toBeInTheDocument();
    // No supplier edges in the fixture -> upstream is an honest dash.
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1);
    // Downstream falls back to the real cascade chain (DLF, parent 1).
    expect(screen.getAllByText('DLF').length).toBeGreaterThanOrEqual(1);
  });
});

describe('DeckEconomicChain (chart 9)', () => {
  it('renders the mechanism backbone with a horizon label per step', () => {
    render(<DeckEconomicChain graph={graph} companies={companies} />);
    expect(screen.getByText('Borrowing Costs ↑')).toBeInTheDocument();
    // Both companies are reachable from the mechanism -> both horizons.
    expect(screen.getByText('Immediate · Medium-Term')).toBeInTheDocument();
  });

  it('renders an honest empty state when no chain applies (never a silent blank)', () => {
    const noMech: ImpactGraph = { ...graph, nodes: graph.nodes.filter((n) => n.kind !== 'mechanism') };
    render(<DeckEconomicChain graph={noMech} companies={companies} />);
    expect(screen.getByText(/No general transmission mechanism applies/)).toBeInTheDocument();
  });
});

describe('DeckKnowledge (chart 10)', () => {
  it('renders every node with a relation legend and pruned toggle', () => {
    render(<DeckKnowledge graph={graph} companies={companies} />);
    expect(screen.getByText('Knowledge Graph')).toBeInTheDocument();
    expect(screen.getAllByText('HDFCBANK').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Hide 1 pruned/)).toBeInTheDocument();
    // Legend lists only relations present in the graph.
    expect(screen.getByText('credit_cost')).toBeInTheDocument();
    expect(screen.queryByText('currency')).toBeNull();
  });
});
