/* One stock row on the card back (spec v2 §7): [TICKER] [CAP TAG]
   [LIQ TAG] ... [(i)] then impact [bar] score. Tapping the row -> deep
   dive; tapping (i) -> business popup (stop propagation so the row
   doesn't also open). Low-delivery warning fires below the row. */
import type { LayerRow } from './api';
import CompanyLogo from './CompanyLogo';
import { bandClass, capClass, fmtPct, isLowDelivery, liqShort, moveColor } from './format';

export default function StockRow({
  row,
  onOpenDeepDive,
  onOpenInfo,
}: {
  row: LayerRow;
  onOpenDeepDive: (ticker: string) => void;
  onOpenInfo: (row: LayerRow) => void;
}) {
  const score = row.intensity?.score ?? null;
  return (
    <div>
      <div className="srow" onClick={() => onOpenDeepDive(row.ticker)} data-testid={`srow-${row.ticker}`}>
        <CompanyLogo logoUrl={row.logo_url} ticker={row.ticker} sector={row.sector} size="sm" />
        <span className="tkr">{row.ticker}</span>
        {/* No tag at all when the company has no honest India cap tier
            (foreign listings, stale caps) -- a "—" chip reads as broken. */}
        {row.cap_tier !== null && (
          <span className={`tag ${capClass(row.cap_tier)}`}>{row.cap_tier}</span>
        )}
        {row.liquidity_tier !== null && (
          <span className={`liq liq-${liqShort(row.liquidity_tier)}`}>{liqShort(row.liquidity_tier)}</span>
        )}
        {row.is_exposure_only || row.excess_move_pct == null ? (
          <span className="rmv" style={{ color: 'var(--ink3)' }}>
            exposure
          </span>
        ) : (
          <span className="rmv" style={{ color: moveColor(row.excess_move_pct) }}>
            {fmtPct(row.excess_move_pct)}
          </span>
        )}
        {score != null ? (
          <>
            <span className="bw">
              <span className={`bar ${bandClass(score)}`} style={{ width: `${score}%` }} />
            </span>
            <span className="sc">{score}</span>
          </>
        ) : (
          <>
            <span className="bw" />
            <span className="sc">—</span>
          </>
        )}
        <button
          className="ib"
          aria-label={`About ${row.ticker}`}
          onClick={(event) => {
            event.stopPropagation();
            onOpenInfo(row);
          }}
        >
          i
        </button>
      </div>
      {isLowDelivery(row.delivery_pct) && (
        <div className="warn">
          ⚠ {Math.round(row.delivery_pct!)}% delivery — much of this move was intraday
        </div>
      )}
    </div>
  );
}
