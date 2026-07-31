// The one company-node design shared by every chart (reference: docs/
// charts-reference.png). The percentage on the node face is the MEASURED
// move (excess_move_pct, chart-spec Doc-1 §2) -- never the LLM's
// magnitude prediction and never confidence_score. A company with no
// measurement degrades to the direction glyph alone; that honest
// fallback replaces the exact bug (magnitude/confidence beside an arrow)
// that made every prior chart read wrong.

// 1 decimal max, trailing ".0" trimmed, explicit "+" on positive values
// (negative values already carry their own "-") -- the sign comes from
// the measured number itself, not a second lookup against direction.
function formatExcess(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  return rounded > 0 ? `+${text}` : text;
}

export interface CompanyNodeProps {
  name: string;
  ticker: string;
  direction?: string | null;
  // The measured move (excess vs sector). Null/undefined -> glyph only.
  excessMovePct?: number | null;
  // Confidence Tree (#5) only -- every other chart's percentage line is
  // magnitude, never confidence (see the file-level comment). Confidence
  // Tree's entire purpose is grading companies BY confidence, so it needs
  // the number too; passing it here adds a separate, explicitly labeled
  // "Confidence: N%" line rather than substituting it into the direction-
  // glyph line, so it can never be mistaken for a magnitude reading.
  confidenceScore?: number | null;
  inMyHoldings?: boolean;
  onClick?: () => void;
  selected?: boolean;
  // Overrides the default fixed 120px tile width -- used by Knowledge Graph
  // to size a node by confidence_score.
  width?: number;
}

export default function CompanyNode({
  name,
  ticker,
  direction,
  excessMovePct,
  confidenceScore,
  inMyHoldings = false,
  onClick,
  selected = false,
  width,
}: CompanyNodeProps) {
  const bearish = direction === 'bearish';
  const glyph = bearish ? '▼' : '▲';
  const toneClass = bearish ? 'text-bearish' : 'text-bullish';

  const content = (
    <>
      <span className="truncate font-editorial text-xs text-ink">{name}</span>
      <span className="font-data text-[10px] text-muted">{ticker}</span>
      <span className={`font-data text-[11px] ${toneClass}`}>
        {glyph} {excessMovePct != null ? `${formatExcess(excessMovePct)}%` : null}
      </span>
      {confidenceScore != null && (
        <span className="font-data text-[10px] text-muted">Confidence: {confidenceScore}%</span>
      )}
    </>
  );

  const className = `flex ${width == null ? 'w-[120px]' : ''} flex-col gap-0.5 rounded-[10px] border bg-elevated p-2 text-left ${
    selected ? 'border-ink' : 'border-hairline'
  } ${inMyHoldings ? 'ring-2 ring-accent-secondary' : ''}`;
  const style = width != null ? { width } : undefined;

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
