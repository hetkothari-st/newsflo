import type { ImpactGraph } from '../../../lib/api';
import { ringsByImpactLevel } from './model';

// Each GraphNodeChip is a fixed w-40 (160px) wide tile -- ring spacing
// must clear that width with real margin, or chips on adjacent rings can
// visually overlap (a real risk flagged by review, since this layout
// can't be checked in a browser in this environment).
const RING_SPACING = 240;

function placeRing(positions: Record<string, { x: number; y: number }>, ids: string[], ringIndex: number) {
  const radius = ringIndex * RING_SPACING;
  const count = ids.length;
  ids.forEach((id, i) => {
    const angle = (2 * Math.PI * i) / count;
    positions[id] = { x: radius * Math.cos(angle), y: radius * Math.sin(angle) };
  });
}

// Pure layout math for the Ripple Effect Graph (#2) -- news at the center,
// mechanism/sector nodes on one middle ring, then company nodes on
// successive rings by impact_level (direct innermost). Framework-
// independent (no React Flow types here) so it's unit-testable without
// mounting any chart.
export function ripplePositions(graph: ImpactGraph): Record<string, { x: number; y: number }> {
  const positions: Record<string, { x: number; y: number }> = {};

  const news = graph.nodes.find((n) => n.kind === 'news');
  if (news) positions[news.id] = { x: 0, y: 0 };

  const midLayer = graph.nodes.filter((n) => n.kind === 'mechanism' || n.kind === 'sector');
  if (midLayer.length > 0) placeRing(positions, midLayer.map((n) => n.id), 1);

  ringsByImpactLevel(graph).forEach((ring, ringIndex) => {
    placeRing(positions, ring.nodes.map((n) => n.id), ringIndex + 2);
  });

  return positions;
}
