// Per-chart availability (user rule 2026-07-31): a chart with no data for
// this alert -- whether sparse resolution or simply the wrong kind of news
// (e.g. a company-specific event has no macro transmission chain) -- is
// HIDDEN from the deck entirely, not rendered as an empty state. Charts
// keep their internal empty-state guards as defense-in-depth; this module
// is the single source of truth for what the deck page shows.
import type { AlertCompany, ImpactGraph } from '../../../lib/api';
import { chainTree, mechanismBackbone } from '../graph/model';

export interface DeckChartAvailability {
  companies: AlertCompany[];
  graph: ImpactGraph;
}

// Returns the CANONICAL chart numbers (Doc-1/Doc-2 numbering) that have
// data, ascending. The deck page renumbers the survivors sequentially for
// display (user rule: skipped charts must not leave gaps in the rail).
export function availableChartNumbers({ companies, graph }: DeckChartAvailability): number[] {
  const hasCompanies = companies.length > 0;
  const hasGraph = graph.nodes.length > 1;
  const { direct, upstream, downstream } = chainTree(graph, companies);

  const available: Record<number, boolean> = {
    1: hasCompanies,
    2: hasGraph,
    // A supply chain of just the direct company (both side columns "—")
    // carries no chain information -- hide it.
    3: direct !== null && upstream.length + downstream.length > 0,
    4: hasCompanies,
    5: hasCompanies,
    6: hasCompanies,
    7: hasCompanies,
    8: hasCompanies,
    // Company-specific event types have no rulebook chain (get_chain
    // returns None) -- correct, not a gap; the chart just doesn't apply.
    9: mechanismBackbone(graph).length > 0,
    // Nodes with zero edges is a scatter, not a knowledge graph.
    10: hasGraph && graph.edges.length > 0,
  };

  return Object.entries(available)
    .filter(([, ok]) => ok)
    .map(([n]) => Number(n))
    .sort((a, b) => a - b);
}
