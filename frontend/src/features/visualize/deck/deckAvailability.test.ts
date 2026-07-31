import { describe, expect, it } from 'vitest';
import type { ImpactGraph } from '../../../lib/api';
import { availableChartNumbers } from './deckAvailability';
import { company, sparseCompanies } from './fixtures';

const emptyGraph: ImpactGraph = { nodes: [], edges: [], gaps: [] };

const richGraph: ImpactGraph = {
  nodes: [
    { id: 'news', kind: 'news', label: 'n' },
    { id: 'mech:borrowing_costs_up', kind: 'mechanism', label: 'Borrowing Costs ↑' },
    { id: 'sector:banking', kind: 'sector', label: 'banking' },
    { id: 'company:1', kind: 'company', company_id: 1, ticker: 'HDFCBANK', label: 'HDFC Bank', name: 'HDFC Bank', direction: 'bearish', impact_level: 'direct' },
    { id: 'company:2', kind: 'company', company_id: 2, ticker: 'DLF', label: 'DLF', name: 'DLF', direction: 'bearish', impact_level: 'indirect_l1' },
  ],
  edges: [
    { from: 'news', to: 'mech:borrowing_costs_up', relation: 'credit_cost', direction: 'bearish', note: 'n', source: 'rulebook_verified' },
    { from: 'sector:banking', to: 'company:1', relation: 'demand', direction: 'bearish', note: 'n', source: 'llm_only' },
  ],
  gaps: [],
};

describe('availableChartNumbers', () => {
  it('shows all ten charts when companies, chain, mechanisms, and edges all exist', () => {
    expect(availableChartNumbers({ companies: sparseCompanies, graph: richGraph })).toEqual(
      [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    );
  });

  it('hides every chart when the alert has no companies and no graph', () => {
    expect(availableChartNumbers({ companies: [], graph: emptyGraph })).toEqual([]);
  });

  it('hides Economic Chain (9) when the event type has no mechanism chain', () => {
    const noMech: ImpactGraph = { ...richGraph, nodes: richGraph.nodes.filter((n) => n.kind !== 'mechanism') };
    const numbers = availableChartNumbers({ companies: sparseCompanies, graph: noMech });
    expect(numbers).not.toContain(9);
    expect(numbers).toContain(1);
  });

  it('hides Supply Chain (3) when there is nothing upstream or downstream', () => {
    // Single direct company, no supplier/customer edges, no cascade children.
    const lone = [company({ company_id: 1, ticker: 'TCS', impact_level: 'direct', parent_company_id: null })];
    const numbers = availableChartNumbers({ companies: lone, graph: richGraph });
    expect(numbers).not.toContain(3);
  });

  it('hides Knowledge Graph (10) when the graph has no edges', () => {
    const noEdges: ImpactGraph = { ...richGraph, edges: [] };
    const numbers = availableChartNumbers({ companies: sparseCompanies, graph: noEdges });
    expect(numbers).not.toContain(10);
    expect(numbers).toContain(2); // ripple only needs nodes
  });
});
