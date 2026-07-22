import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from 'd3-force';
import type { ImpactGraph } from '../../../lib/api';
import { ringsByImpactLevel } from './model';

// Each GraphNodeChip is a fixed w-40 (160px) wide tile -- ring spacing
// must clear that width with real margin, or chips on adjacent rings can
// visually overlap (a real risk flagged by review, since this layout
// can't be checked in a browser in this environment).
const RING_SPACING = 240;

// Bug (found comparing a live render to the reference mockup): angle was
// (2*PI*i)/count with no per-ring term, so a single-node ring (the common
// sparse-data case -- one company at a given impact level) always placed
// its lone node at angle 0 regardless of ringIndex. Every ring's i=0 node
// then landed on the positive x-axis, so a chain of single-node rings
// produced a perfectly flat, collinear row (y=0 for every node) instead of
// a ripple. RING_ANGLE_OFFSET staggers each ring by 30 degrees, keyed off
// (ringIndex + 1) so the offset is never zero even for ringIndex 0 --
// guaranteeing a non-zero angle (and therefore non-zero y) for a
// single-node ring at any ring index, not just the ones this app's real
// callers happen to use today.
const RING_ANGLE_OFFSET = Math.PI / 6;

function placeRing(positions: Record<string, { x: number; y: number }>, ids: string[], ringIndex: number) {
  const radius = ringIndex * RING_SPACING;
  const count = ids.length;
  const ringOffset = ((ringIndex + 1) * RING_ANGLE_OFFSET) % (2 * Math.PI);
  ids.forEach((id, i) => {
    const angle = ringOffset + (2 * Math.PI * i) / count;
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

interface SimNode {
  id: string;
  x?: number;
  y?: number;
}

// One-shot (not live-animated) force simulation: run a fixed number of
// ticks synchronously, then return the settled positions. A live/
// continuously-animated simulation would be more visually dynamic but is
// materially riskier to get right without browser access to actually see
// it settle -- a deterministic tick count keeps this reliable and fast.
// Positions ARE non-deterministic between calls (d3-force's default
// internal RNG jitters initial placement) -- callers/tests must never
// assert exact coordinates, only structural properties (finite, no throw).
export function forceDirectedPositions(graph: ImpactGraph): Record<string, { x: number; y: number }> {
  const nodes: SimNode[] = graph.nodes.map((n) => ({ id: n.id }));
  if (nodes.length === 0) return {};

  const links = graph.edges
    .filter((e) => graph.nodes.some((n) => n.id === e.from) && graph.nodes.some((n) => n.id === e.to))
    .map((e) => ({ source: e.from, target: e.to }));

  // forceCollide's radius must clear the WIDEST node this graph can render,
  // or high-confidence company nodes (KnowledgeGraph.tsx sizes them up to
  // 120 + 100*0.6 = 180px wide, half-width 90px) can still settle closer
  // than their own half-width apart and visually overlap -- 70 (half of
  // GraphFlowNode's old flat 160px chip) was already too small for that,
  // and is smaller still now that the widest node can reach 180px.
  const COLLIDE_RADIUS = 100;

  const simulation = forceSimulation(nodes)
    .force('link', forceLink(links).id((d) => (d as SimNode).id).distance(140))
    .force('charge', forceManyBody().strength(-260))
    .force('center', forceCenter(0, 0))
    .force('collide', forceCollide(COLLIDE_RADIUS))
    .stop();

  for (let i = 0; i < 300; i += 1) simulation.tick();

  const positions: Record<string, { x: number; y: number }> = {};
  for (const node of nodes) {
    positions[node.id] = { x: node.x ?? 0, y: node.y ?? 0 };
  }
  return positions;
}
