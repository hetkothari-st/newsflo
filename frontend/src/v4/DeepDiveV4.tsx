/* v4 deep dive -- the "inside page": a full-bleed ink overlay opened
   from any company row, like turning to an inside spread of the
   broadsheet. Functional parity with the v3 deep-dive sheet: measured
   numbers, intensity build-up, risk warnings, sector peers, official
   classification, and the why-it's-here reasoning. */
import { useEffect, useState } from 'react';
import { getStockDeepDive, type StockDeepDive } from '../v3/api';
import { isLowDelivery, isThinTrading } from '../v3/format';
import { useAuth } from '../lib/auth';

function fmtPct(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

export default function DeepDiveV4({
  ticker,
  alertId,
  onOpenPeer,
  onClose,
}: {
  ticker: string;
  alertId?: number;
  onOpenPeer: (ticker: string, alertId?: number) => void;
  onClose: () => void;
}) {
  const { token } = useAuth();
  const [data, setData] = useState<StockDeepDive | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    getStockDeepDive(ticker, alertId, token, 'en')
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker, alertId, token]);

  const warnings: string[] = [];
  if (data !== null && isLowDelivery(data.delivery_pct)) {
    warnings.push(
      `Only ${Math.round(data.delivery_pct!)}% of volume went to delivery — much of this move was intraday speculation, not accumulation.`,
    );
  }
  if (data !== null && isThinTrading(data.liquidity_tier, data.cap_tier)) {
    warnings.push('Small size and thin trading amplify moves both ways; exiting can be hard — higher risk.');
  }

  return (
    <div className="inside" role="dialog" aria-label={`Deep dive ${ticker}`}>
      <button className="iclose" onClick={onClose}>
        Back to the front page ×
      </button>
      {error !== null && <p className="bandempty">{error}</p>}
      {data === null && error === null && <p className="bandempty">Setting the type…</p>}
      {data !== null && (
        <>
          <div className="istamp">{data.name}</div>
          <div className="isub">
            {data.ticker} — {data.sector.replace(/_/g, ' ')}
            {data.cap_tier !== null && ` — ${data.cap_tier} cap`}
            {data.pe != null && ` — PE ${data.pe.toFixed(1)}`}
          </div>
          <div className="inums">
            {data.excess_move_pct !== null && (
              <span>
                <span className="l4">Excess vs sector</span>
                <span className={`v4 ${data.excess_move_pct < 0 ? 'down' : 'up'}`} style={{ display: 'block' }}>
                  {fmtPct(data.excess_move_pct)}
                </span>
              </span>
            )}
            <span>
              <span className="l4">Raw / sector</span>
              <span className="v4" style={{ display: 'block' }}>
                {data.raw_move_pct != null ? data.raw_move_pct.toFixed(1) : '—'} /{' '}
                {data.sector_move_pct != null ? data.sector_move_pct.toFixed(1) : '—'}
              </span>
            </span>
            <span>
              <span className="l4">Volume</span>
              <span className="v4" style={{ display: 'block' }}>
                {data.volume_multiple != null ? `${data.volume_multiple.toFixed(1)}×` : '—'}
              </span>
            </span>
            {data.intensity !== null && (
              <span>
                <span className="l4">{data.intensity.band} intensity</span>
                <span className="v4" style={{ display: 'block' }}>
                  {data.intensity.score}
                </span>
              </span>
            )}
          </div>

          {data.intensity !== null && data.intensity.components.length > 0 && (
            <div className="isec">
              <p className="ilab">How this score is built — {data.intensity.components.length} signals</p>
              {data.intensity.components.map((component) => (
                <div className="comp4" key={component.label}>
                  <span className="cl">{component.label}</span>
                  <span className="cbar">
                    <i style={{ width: `${Math.min(100, Math.max(0, component.score))}%` }} />
                  </span>
                  <span className="cv">{Math.round(component.contribution)}</span>
                </div>
              ))}
            </div>
          )}

          {warnings.map((warning) => (
            <p className="iwarn" key={warning}>
              ⚠ {warning}
            </p>
          ))}

          {data.peers.length > 0 && (
            <div className="isec">
              <p className="ilab">Sector peers — by intensity</p>
              {data.peers.map((peer) => (
                <div
                  className="crow"
                  key={peer.ticker}
                  onClick={() => onOpenPeer(peer.ticker, alertId)}
                  data-testid={`v4peer-${peer.ticker}`}
                >
                  <div className="cmain">
                    <span className="nm4">{peer.name}</span>
                    {peer.is_exposure_only || peer.excess_move_pct == null ? (
                      <span className="mv4 mvx">exposure</span>
                    ) : (
                      <span className={`mv4 ${peer.excess_move_pct < 0 ? 'down' : 'up'}`}>
                        {fmtPct(peer.excess_move_pct)}
                      </span>
                    )}
                  </div>
                  <div className="cmeta">
                    <span>{peer.ticker}</span>
                    {peer.cap_tier !== null && <span>{peer.cap_tier} cap</span>}
                  </div>
                </div>
              ))}
            </div>
          )}

          {data.fundamentals && (
            <div className="isec">
              <p className="ilab">What they do — {data.fundamentals.source}</p>
              <p>
                {[
                  data.fundamentals.classification.sector,
                  data.fundamentals.classification.industry,
                  data.fundamentals.classification.group,
                  data.fundamentals.classification.sub_group,
                ]
                  .filter(Boolean)
                  .join(' — ')}
              </p>
            </div>
          )}

          {(data.why !== null || data.rationale !== null) && (
            <div className="isec">
              <p className="ilab">
                {data.section_title !== null
                  ? `Why it's under "${data.section_title}"`
                  : 'Why it appears in this story'}
              </p>
              <ul>
                {data.why !== null && <li>{data.why}</li>}
                {data.rationale !== null && data.rationale !== data.why && <li>{data.rationale}</li>}
              </ul>
            </div>
          )}

          <div className="isec">
            <p className="ilab">
              Intensity measures how hard the news hit this stock — not whether it's a good
              investment. Percentages are measured market moves, not forecasts.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
