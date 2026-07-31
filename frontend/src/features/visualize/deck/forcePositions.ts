import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from 'd3-force';
import type { ImpactGraph } from '../../../lib/api';

interface SimNode {
  id: string;
  x?: number;
  y?: number;
}

// Deck-local force layout for the Knowledge Graph (#10). Differs from the
// older graph/layout.ts::forceDirectedPositions in one load-bearing way:
// forceX/forceY pull EVERY node gently toward the origin. Real alert graphs
// are sparse (live 9002: 13 nodes, 4 edges) -- without a centering pull,
// charge repulsion scatters the unlinked nodes to ±700px and no legible
// zoom can fit them in a phone-width pane (verified in a live screenshot:
// an apparently-empty chart). With the pull, the bounding box stays within
// roughly ±350px, which fitView can show at a readable zoom.
//
// One-shot deterministic tick count; d3's internal RNG still jitters exact
// positions -- callers/tests assert structure (finite, all ids present),
// never coordinates.
export function deckForcePositions(graph: ImpactGraph): Record<string, { x: number; y: number }> {
  const nodes: SimNode[] = graph.nodes.map((n) => ({ id: n.id }));
  if (nodes.length === 0) return {};

  const links = graph.edges
    .filter((e) => graph.nodes.some((n) => n.id === e.from) && graph.nodes.some((n) => n.id === e.to))
    .map((e) => ({ source: e.from, target: e.to }));

  // Collide radius must clear the widest node (confidence-sized company
  // nodes reach 120 + 100*0.6 = 180px, half-width 90) -- see the same
  // constant's history in graph/layout.ts.
  const COLLIDE_RADIUS = 100;

  const simulation = forceSimulation(nodes)
    .force('link', forceLink(links).id((d) => (d as SimNode).id).distance(140))
    .force('charge', forceManyBody().strength(-260))
    .force('x', forceX(0).strength(0.12))
    .force('y', forceY(0).strength(0.12))
    .force('collide', forceCollide(COLLIDE_RADIUS))
    .stop();

  for (let i = 0; i < 300; i += 1) simulation.tick();

  const positions: Record<string, { x: number; y: number }> = {};
  for (const node of nodes) {
    positions[node.id] = { x: node.x ?? 0, y: node.y ?? 0 };
  }
  return positions;
}
