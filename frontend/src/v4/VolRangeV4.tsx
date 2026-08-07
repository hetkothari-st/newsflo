/* v4 volatility range -- the empirical reaction range (subsystem D)
   drawn as an editorial rule instead of the deployed version's plain
   text line: a hairline scale, the typical band as a solid ink rule,
   a tick at the median, and (when measured) this stock's actual move
   pinned on the same scale. When the move falls outside the usual band
   the scale stretches to include it and says so. */
import type { VolatilityRangeData } from '../components/VolatilityRange';

const pct = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}%`;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export default function VolRangeV4({
  range,
  move,
}: {
  range: VolatilityRangeData;
  move?: number | null;
}) {
  // Scale spans the band, stretched to include the actual move when it
  // lands outside -- the pin must sit on the scale, never off-canvas.
  const lo = Math.min(range.min_excess_move_pct, move ?? range.min_excess_move_pct);
  const hi = Math.max(range.max_excess_move_pct, move ?? range.max_excess_move_pct);
  const span = hi - lo || 1;
  const pos = (v: number) => ((v - lo) / span) * 100;
  const outside =
    move != null && (move < range.min_excess_move_pct || move > range.max_excess_move_pct);
  return (
    <div className="vr4">
      {move != null && (
        <div className="vr4-cur">
          <div className="vr4-curm" style={{ left: `${clamp(pos(move), 4, 96)}%` }}>
            <span className={`vr4-curv ${move < 0 ? 'down' : 'up'}`}>
              this move {pct(move)}
              {outside ? ' · outside the usual band' : ''}
            </span>
            <span className="vr4-pin" aria-hidden="true" />
          </div>
        </div>
      )}
      <div className="vr4-track">
        <span
          className="vr4-band"
          style={{
            left: `${pos(range.min_excess_move_pct)}%`,
            width: `${pos(range.max_excess_move_pct) - pos(range.min_excess_move_pct)}%`,
          }}
        />
        <span className="vr4-tick" style={{ left: `${pos(range.median_excess_move_pct)}%` }} />
      </div>
      <div className="vr4-scale">
        <span style={{ left: `${clamp(pos(range.min_excess_move_pct), 5, 95)}%` }}>
          {pct(range.min_excess_move_pct)}
        </span>
        <span className="med" style={{ left: `${clamp(pos(range.median_excess_move_pct), 18, 82)}%` }}>
          median {pct(range.median_excess_move_pct)}
        </span>
        <span style={{ left: `${clamp(pos(range.max_excess_move_pct), 5, 95)}%` }}>
          {pct(range.max_excess_move_pct)}
        </span>
      </div>
      <p className="vr4-n">
        {range.level === 'SECTOR' ? 'sector-level · ' : ''}
        {range.n_events} measured events · as of {range.as_of}
      </p>
    </div>
  );
}
