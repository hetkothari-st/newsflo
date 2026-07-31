// Pure geometry for the Ripple Effect chart (#2): news at the origin,
// mechanism/sector nodes on the first ring, company nodes on successive
// rings by impact_level (direct innermost). Everything is computed here so
// the chart renders as ONE static, fully-visible SVG -- no pan/zoom, no
// viewport centering that can leave the pane looking empty or scattered
// (the reported "always distorted" failure of the React Flow version).
import type { GraphNode, ImpactGraph } from '../../../lib/api';
import { ringsByImpactLevel } from '../graph/model';

export const RADIAL = {
  BASE_RADIUS: 150, // first ring's distance from the news node
  RING_STEP: 120, // spacing between successive rings
  NODE_W: 104, // company node box
  NODE_H: 66, // fits CompanyNode's three text lines unclipped
  MID_W: 110, // mechanism/sector node box
  MID_H: 44,
  NEWS_W: 148,
  NEWS_H: 56,
  PAD: 16, // outer padding around the fitted bounds
} as const;

export interface RadialNodePos {
  node: GraphNode;
  x: number; // box top-left
  y: number;
  w: number;
  h: number;
  cx: number; // box center (edge anchor)
  cy: number;
}

export interface RadialLayoutResult {
  nodes: RadialNodePos[];
  ringRadii: number[];
  // Fitted viewBox (centered on the news node at 0,0).
  minX: number;
  minY: number;
  width: number;
  height: number;
}

// Distributes ring nodes evenly with a per-ring angular offset -- a lone
// node on ring i must NOT sit at the same angle as a lone node on ring
// i+1, or sparse alerts collapse into one straight line (the Doc-2 §4
// collinearity bug, solved the same way graph/layout.ts::placeRing does).
function ringAngle(ringIndex: number, i: number, count: number): number {
  const offset = ((ringIndex + 1) * Math.PI) / 6;
  return offset + (2 * Math.PI * i) / count;
}

// A ring must be wide enough that its boxes cannot overlap: grow the
// radius until the circumference fits every box with breathing room.
function ringRadius(ringIndex: number, count: number, boxW: number): number {
  const nominal = RADIAL.BASE_RADIUS + ringIndex * RADIAL.RING_STEP;
  const needed = (count * (boxW + 24)) / (2 * Math.PI);
  return Math.max(nominal, needed);
}

export function radialLayout(graph: ImpactGraph): RadialLayoutResult {
  const nodes: RadialNodePos[] = [];
  const ringRadii: number[] = [];

  const place = (node: GraphNode, cx: number, cy: number, w: number, h: number) => {
    nodes.push({ node, cx, cy, x: cx - w / 2, y: cy - h / 2, w, h });
  };

  const news = graph.nodes.find((n) => n.kind === 'news');
  if (news) place(news, 0, 0, RADIAL.NEWS_W, RADIAL.NEWS_H);

  const ringSpecs: { members: GraphNode[]; w: number; h: number }[] = [];
  const midLayer = graph.nodes.filter((n) => n.kind === 'mechanism' || n.kind === 'sector');
  if (midLayer.length > 0) ringSpecs.push({ members: midLayer, w: RADIAL.MID_W, h: RADIAL.MID_H });
  for (const ring of ringsByImpactLevel(graph)) {
    ringSpecs.push({ members: ring.nodes, w: RADIAL.NODE_W, h: RADIAL.NODE_H });
  }

  ringSpecs.forEach((spec, ringIndex) => {
    const radius = ringRadius(ringIndex, spec.members.length, spec.w);
    ringRadii.push(radius);
    spec.members.forEach((node, i) => {
      const angle = ringAngle(ringIndex, i, spec.members.length);
      place(node, radius * Math.cos(angle), radius * Math.sin(angle), spec.w, spec.h);
    });
  });

  // Fit the viewBox to everything drawn: node boxes AND ring guides.
  const maxRadius = ringRadii.length > 0 ? Math.max(...ringRadii) : 0;
  let minX = -maxRadius;
  let minY = -maxRadius;
  let maxX = maxRadius;
  let maxY = maxRadius;
  for (const n of nodes) {
    minX = Math.min(minX, n.x);
    minY = Math.min(minY, n.y);
    maxX = Math.max(maxX, n.x + n.w);
    maxY = Math.max(maxY, n.y + n.h);
  }
  minX -= RADIAL.PAD;
  minY -= RADIAL.PAD;
  maxX += RADIAL.PAD;
  maxY += RADIAL.PAD;

  return { nodes, ringRadii, minX, minY, width: maxX - minX, height: maxY - minY };
}
