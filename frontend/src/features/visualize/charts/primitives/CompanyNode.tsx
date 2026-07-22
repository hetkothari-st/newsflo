// The one company-node design shared by every chart (reference: docs/
// charts-reference.png). Deliberately generic over its data source -- an
// AlertCompany-backed chart passes magnitudeLow/High (a real range); a
// GraphNode-backed chart (Ripple, Knowledge Graph) has no magnitude at all,
// so the percentage line degrades to a direction glyph alone rather than
// showing confidence_score in its place (that swap is the exact bug this
// component replaces three separate ad-hoc chip designs to fix).

// 1 decimal max, trailing ".0" trimmed, explicit "+" on positive values
// (negative values already carry their own "-"). magnitude_low/high are
// already signed per the backend's convention (bearish = negative), so the
// sign comes from the number itself, not a second lookup against direction.
function formatMagnitude(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  return rounded > 0 ? `+${text}` : text;
}

function magnitudeLabel(low: number, high: number): string {
  const lowText = formatMagnitude(low);
  const highText = formatMagnitude(high);
  return lowText === highText ? `${lowText}%` : `${lowText}%–${highText}%`;
}

export interface CompanyNodeProps {
  name: string;
  ticker: string;
  direction?: string | null;
  magnitudeLow?: number | null;
  magnitudeHigh?: number | null;
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
  magnitudeLow,
  magnitudeHigh,
  confidenceScore,
  inMyHoldings = false,
  onClick,
  selected = false,
  width,
}: CompanyNodeProps) {
  const bearish = direction === 'bearish';
  const glyph = bearish ? '▼' : '▲';
  const toneClass = bearish ? 'text-bearish' : 'text-bullish';
  const hasMagnitude = magnitudeLow != null && magnitudeHigh != null;

  const content = (
    <>
      <span className="truncate font-editorial text-xs text-ink">{name}</span>
      <span className="font-data text-[10px] text-muted">{ticker}</span>
      <span className={`font-data text-[11px] ${toneClass}`}>
        {glyph} {hasMagnitude ? magnitudeLabel(magnitudeLow, magnitudeHigh) : null}
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
