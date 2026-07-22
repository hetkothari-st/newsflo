import type { GraphNode } from '../../../../lib/api';
import CompanyNode from './CompanyNode';
import SectorNode from './SectorNode';
import MechanismPill from './MechanismPill';

// Dispatches an ImpactGraph node to the ONE matching Phase 1 primitive by
// kind -- the shared node-link chart renderer for Ripple Effect Graph (#2)
// and Knowledge Graph (#10), replacing the older, chart-specific
// GraphNodeChip (160px, its own three-line layout duplicate of what
// CompanyNode now is).
export default function GraphFlowNode({
  node,
  onClick,
  selected = false,
  width,
}: {
  node: GraphNode;
  onClick?: () => void;
  selected?: boolean;
  // Confidence-driven sizing (Knowledge Graph only) -- meaningful for
  // company nodes only, since only they carry a real confidence_score.
  width?: number;
}) {
  if (node.kind === 'company') {
    return (
      <CompanyNode
        name={node.name ?? node.label}
        ticker={node.ticker ?? node.label}
        direction={node.direction}
        inMyHoldings={node.in_my_holdings}
        onClick={onClick}
        selected={selected}
        width={width}
      />
    );
  }
  if (node.kind === 'sector') {
    return <SectorNode sector={node.label} onClick={onClick} selected={selected} />;
  }
  if (node.kind === 'mechanism') {
    return <MechanismPill label={node.label} />;
  }
  // news
  return (
    <div className="flex w-[140px] flex-col items-center gap-0.5 rounded-[10px] border border-hairline bg-elevated p-2 text-center">
      <span className="font-data text-[9px] uppercase tracking-widest text-muted">News</span>
      <span className="line-clamp-2 font-editorial text-[11px] text-ink">{node.label}</span>
    </div>
  );
}
