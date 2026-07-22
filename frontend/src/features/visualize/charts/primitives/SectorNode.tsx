import { sectorColor } from '../../colors';
import { sectorLabel } from '../../transforms';

// Same rect as CompanyNode, border colored by the sector's own palette
// entry instead of a selection state, label + a count instead of three
// data lines -- graph-chart sector nodes (Ripple, Knowledge Graph) never
// carry per-company data, only how many companies sit under them.
export default function SectorNode({
  sector,
  count,
  onClick,
  selected = false,
}: {
  sector: string;
  count?: number;
  onClick?: () => void;
  selected?: boolean;
}) {
  const color = sectorColor(sector);
  const className = `flex w-[120px] flex-col gap-0.5 rounded-[10px] border bg-elevated p-2 text-left ${
    selected ? 'border-ink' : ''
  }`;
  const style = { borderColor: selected ? undefined : color, borderWidth: selected ? undefined : 1.5 };

  const content = (
    <>
      <span className="font-data text-[10px] uppercase tracking-widest text-muted">Sector</span>
      <span className="truncate font-editorial text-xs text-ink">
        {sectorLabel(sector)}
        {count != null && <span className="font-data text-[10px] text-muted"> ({count})</span>}
      </span>
    </>
  );

  if (!onClick) {
    return (
      <div className={className} style={style}>
        {content}
      </div>
    );
  }

  return (
    <button type="button" onClick={onClick} aria-pressed={selected} className={className} style={style}>
      {content}
    </button>
  );
}
