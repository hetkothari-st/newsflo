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

export interface ChainTree {
  direct: GraphNode | null;
  upstream: GraphNode[];
  downstream: GraphNode[];
}

// Supply Chain Graph (#3), columnar layout: Upstream (Suppliers) / Direct
// Company / Downstream (Customers). `direct` is the company node whose OWN
// impact_level is "direct" (a real, backend-assigned marker of directly-
// affected companies -- see app.analysis.schemas), not a path-derived
// heuristic: reusing longestChainPath's terminal node would make "direct"
// shift onto whatever company a downstream customer edge happens to reach
// (the longest path simply extends past it), which is backwards -- the
// company a customer edge points AWAY FROM is the direct one, not the one
// it points TO. Falls back to the first company node when none is marked
// "direct" (a legacy/synthesized graph might not carry impact_level) so
// this never returns null just because that one field is missing.
//
// upstream/downstream are populated ONLY from real "supplier"/"customer"
// relation edges already in the graph (see backend app.reasoning.rulebook
// EDGE_RELATIONS) -- never inferred or guessed. Most alerts' cascade edges
// are mechanism/sector/demand-shaped, not literal supplier/customer links,
// so an empty upstream or downstream column is the normal, honest case,
// not a bug (Sparse Data Rule: the column still renders, with a quiet "--").
export function chainTree(graph: ImpactGraph): ChainTree {
  const companyNodes = graph.nodes.filter((n) => n.kind === 'company');
  const direct = companyNodes.find((n) => n.impact_level === 'direct') ?? companyNodes[0] ?? null;
  if (!direct) return { direct: null, upstream: [], downstream: [] };

  const nodesById = new Map(graph.nodes.map((n) => [n.id, n]));
  const upstream = graph.edges
    .filter((e) => e.to === direct.id && e.relation === 'supplier')
    .map((e) => nodesById.get(e.from))
    .filter((n): n is GraphNode => n !== undefined && n.kind === 'company');
  const downstream = graph.edges
    .filter((e) => e.from === direct.id && e.relation === 'customer')
    .map((e) => nodesById.get(e.to))
    .filter((n): n is GraphNode => n !== undefined && n.kind === 'company');

  return { direct, upstream, downstream };
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
