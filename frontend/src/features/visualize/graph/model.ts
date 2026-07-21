import type { Alert, GraphEdge, GraphNode, ImpactGraph } from '../../../lib/api';

function synthesizeLegacyGraph(alert: Alert): ImpactGraph {
  const nodes: GraphNode[] = [{ id: 'news', kind: 'news', label: alert.article.title }];
  const edges: GraphEdge[] = [];
  const seenNodeIds = new Set(['news']);

  for (const company of alert.companies) {
    const companyId = `company:${company.company_id}`;
    if (seenNodeIds.has(companyId)) continue; // defensive: never emit a duplicate node id
    seenNodeIds.add(companyId);
    nodes.push({
      id: companyId, kind: 'company', label: company.name,
      company_id: company.company_id, ticker: company.ticker, name: company.name,
      direction: company.direction, confidence_score: company.confidence_score,
      impact_level: company.impact_level, in_my_holdings: company.in_my_holdings,
    });

    const sector = company.sector && company.sector.trim().length > 0 ? company.sector : null;
    if (sector) {
      const sectorId = `sector:${sector}`;
      if (!seenNodeIds.has(sectorId)) {
        seenNodeIds.add(sectorId);
        nodes.push({ id: sectorId, kind: 'sector', label: sector });
        edges.push({
          from: 'news', to: sectorId, relation: 'correlation', direction: company.direction,
          note: 'This news directly names companies in this sector.', source: 'llm_only',
        });
      }
      edges.push({
        from: sectorId, to: companyId, relation: 'demand', direction: company.direction,
        note: `${company.name} is affected by this news.`, source: 'llm_only',
      });
    } else {
      edges.push({
        from: 'news', to: companyId, relation: 'correlation', direction: company.direction,
        note: 'This news directly names this company.', source: 'llm_only',
      });
    }
  }

  return { nodes, edges, gaps: [] };
}

// Returns alert.graph verbatim when the backend already computed one
// (Phase 4's GET /api/alerts/{id}) -- pruned edges, gaps, and every other
// field pass through unchanged, no re-filtering. Falls back to a minimal
// synthesized graph (news -> sector -> company, no mechanism layer) for a
// legacy alert (predates Phase 3/4) so every graph chart still has a
// consistent ImpactGraph to render, never undefined/a crash.
export function buildGraph(alert: Alert): ImpactGraph {
  if (alert.graph) return alert.graph;
  return synthesizeLegacyGraph(alert);
}

// Supply Chain Graph (#3): the single longest from-"news" path through the
// graph, by edge count. Small graphs, no cycles expected in practice (the
// backend's edge generation is a DAG by construction) -- the `visited`
// guard below is defense-in-depth, not a case this data is expected to hit.
export function longestChainPath(graph: ImpactGraph): GraphNode[] {
  const nodesById = new Map(graph.nodes.map((n) => [n.id, n]));
  const outgoing = new Map<string, GraphEdge[]>();
  for (const edge of graph.edges) {
    const list = outgoing.get(edge.from) ?? [];
    list.push(edge);
    outgoing.set(edge.from, list);
  }

  function longestFrom(nodeId: string, visited: Set<string>): string[] {
    let best: string[] = [nodeId];
    for (const edge of outgoing.get(nodeId) ?? []) {
      if (visited.has(edge.to)) continue;
      const candidate = [nodeId, ...longestFrom(edge.to, new Set(visited).add(edge.to))];
      if (candidate.length > best.length) best = candidate;
    }
    return best;
  }

  if (!nodesById.has('news')) return [];
  return longestFrom('news', new Set(['news']))
    .map((id) => nodesById.get(id))
    .filter((n): n is GraphNode => n !== undefined);
}

// Economic Chain (#9): mechanism-kind nodes only, in their existing order
// (the order _build_graph/synthesizeLegacyGraph already inserted them in --
// insertion order for a dict-backed structure is stable, matching the
// chain's own natural sequence). The chart itself (Phase 7) is responsible
// for labeling each with the time_horizon bucket of the companies it
// reaches -- this selector only narrows down to the relevant nodes.
export function mechanismBackbone(graph: ImpactGraph): GraphNode[] {
  return graph.nodes.filter((n) => n.kind === 'mechanism');
}

export interface ImpactRing {
  level: string; // direct | indirect_l1 | indirect_l2
  nodes: GraphNode[];
}

const RING_ORDER = ['direct', 'indirect_l1', 'indirect_l2'];

// Ripple Effect Graph (#2): company nodes grouped into concentric rings by
// impact_level, direct = innermost. Only company-kind nodes carry
// impact_level, so mechanism/sector/news nodes are never in any ring.
export function ringsByImpactLevel(graph: ImpactGraph): ImpactRing[] {
  return RING_ORDER.map((level) => ({
    level,
    nodes: graph.nodes.filter((n) => n.kind === 'company' && n.impact_level === level),
  })).filter((ring) => ring.nodes.length > 0);
}
