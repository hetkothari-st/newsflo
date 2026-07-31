import type { GraphEdge, GraphNode } from '../../../lib/api';
import GraphFlowNode from '../charts/primitives/GraphFlowNode';
import './deck.css';

// Shared static-SVG renderer for the node-link charts (2 Ripple, 10
// Knowledge). Replaces the React Flow panes: the whole graph is one
// fitted, non-interactive-viewport SVG -- every node visible at once,
// scaled to the container via viewBox, no pan/zoom to end up centered on
// empty space (the reported "always distorted" failure). Nodes stay
// tappable through foreignObject, same as the tree engine.

export interface PositionedNode {
  node: GraphNode;
  x: number;
  y: number;
  w: number;
  h: number;
  cx: number;
  cy: number;
}

export default function DeckGraphSvg({
  positioned,
  edges,
  viewBox,
  ringRadii = [],
  edgeColor,
  selectedId,
  onToggle,
  label,
}: {
  positioned: PositionedNode[];
  edges: GraphEdge[];
  viewBox: { minX: number; minY: number; width: number; height: number };
  // Ripple only: guide circles that make the rings read as rings.
  ringRadii?: number[];
  edgeColor: (edge: GraphEdge) => string;
  selectedId: number | null;
  onToggle: (companyId: number) => void;
  label: string;
}) {
  const byId = new Map(positioned.map((p) => [p.node.id, p]));

  return (
    <svg
      className="deck-graphsvg"
      viewBox={`${viewBox.minX} ${viewBox.minY} ${viewBox.width} ${viewBox.height}`}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label={label}
    >
      {ringRadii.map((radius) => (
        <circle key={radius} className="deck-ringguide" cx={0} cy={0} r={radius} />
      ))}
      {edges.map((edge, i) => {
        const from = byId.get(edge.from);
        const to = byId.get(edge.to);
        if (!from || !to) return null;
        const pruned = edge.source === 'rulebook_pruned';
        return (
          <line
            key={`${edge.from}-${edge.to}-${i}`}
            className="deck-graphedge"
            x1={from.cx}
            y1={from.cy}
            x2={to.cx}
            y2={to.cy}
            stroke={edgeColor(edge)}
            strokeDasharray={pruned ? '4 4' : undefined}
            opacity={pruned ? 0.35 : 0.8}
          />
        );
      })}
      {positioned.map((p) => {
        const isCompany = p.node.kind === 'company' && p.node.company_id != null;
        return (
          <foreignObject key={p.node.id} x={p.x} y={p.y} width={p.w} height={p.h}>
            <div className="deck-nodefit deck-nodefit-center">
              <GraphFlowNode
                node={p.node}
                width={isCompany ? p.w : undefined}
                onClick={isCompany ? () => onToggle(p.node.company_id as number) : undefined}
                selected={isCompany && selectedId === p.node.company_id}
              />
            </div>
          </foreignObject>
        );
      })}
    </svg>
  );
}
