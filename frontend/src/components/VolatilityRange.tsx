// Empirical reaction range for one news category (subsystem D). The
// backend sends this only when real measured events back it; below the
// sample thresholds the field is null and this renders nothing. A
// SECTOR-level range is pooled across the sector and must say so --
// dressing it as stock-specific would lie about sample identity.
export interface VolatilityRangeData {
  level: 'COMPANY' | 'SECTOR';
  n_events: number;
  min_excess_move_pct: number;
  median_excess_move_pct: number;
  max_excess_move_pct: number;
  as_of: string;
}

const pct = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}%`;

export default function VolatilityRange({ range }: { range: VolatilityRangeData | null | undefined }) {
  if (!range) return null;
  return (
    <p className="volrange">
      <span className="vr-label">Typical on this news type</span>
      <span className="vr-nums">
        {pct(range.min_excess_move_pct)} … {pct(range.max_excess_move_pct)}
        {' · '}median {pct(range.median_excess_move_pct)}
      </span>
      <span className="vr-n">
        {range.level === 'SECTOR' ? 'sector-level, ' : ''}
        {range.n_events} events
      </span>
    </p>
  );
}
