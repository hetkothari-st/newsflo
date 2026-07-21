import type { GraphNode } from '../../../../lib/api';
import { sectorColor } from '../../colors';
import { sectorLabel } from '../../transforms';

// Renders any ImpactGraph node (news/mechanism/sector/company) with the
// same visual language as CompanyCard, so a graph chart reads as part of
// the same system as the 6 grouping charts. Company-kind nodes get the
// portfolio ring (in_my_holdings) exactly like CompanyCard does; non-
// company kinds never do (only companies can be "held").
export default function GraphNodeChip({
  node,
  onClick,
  selected = false,
}: {
  node: GraphNode;
  onClick?: () => void;
  selected?: boolean;
}) {
  const isCompany = node.kind === 'company';
  const bearish = node.direction === 'bearish';

  const content = isCompany ? (
    <>
      <span className="font-data text-xs font-semibold text-ink">{node.ticker}</span>
      <span className="truncate font-editorial text-sm text-ink">{node.name}</span>
      {node.confidence_score != null && (
        <span aria-hidden="true" className={`font-data text-xs ${bearish ? 'text-bearish' : 'text-bullish'}`}>
          {bearish ? '▼' : '▲'} {node.confidence_score}%
        </span>
      )}
    </>
  ) : (
    <>
      <span className="font-data text-[10px] uppercase tracking-widest text-muted">
        {node.kind === 'sector' ? 'Sector' : node.kind === 'mechanism' ? 'Mechanism' : 'News'}
      </span>
      <span className="truncate font-editorial text-sm text-ink">
        {node.kind === 'sector' ? sectorLabel(node.label) : node.label}
      </span>
    </>
  );

  const ringClass = isCompany && node.in_my_holdings ? 'ring-2 ring-accent-secondary' : '';
  const sectorBorder = node.kind === 'sector' ? sectorColor(node.label) : undefined;

  const className = `flex w-40 flex-col gap-0.5 rounded-lg border p-2.5 text-left theme-light:shadow-neu-sm ${
    selected ? 'border-ink theme-light:border-ink' : 'border-hairline theme-light:border-transparent'
  } ${ringClass}`;
  const style = sectorBorder ? { borderColor: sectorBorder } : undefined;

  if (!onClick) {
    return <div className={className} style={style}>{content}</div>;
  }

  return (
    <button type="button" onClick={onClick} aria-pressed={selected} className={className} style={style}>
      {content}
    </button>
  );
}
