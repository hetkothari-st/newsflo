/* v4 deep dive -- a paper popup over the current page, in exactly the
   ripple page's visual language: serif name, ruled stats strip, ink
   section strips, ledger peer rows. Functional parity with the deployed
   deep-dive sheet: measured numbers, intensity build-up, risk warnings,
   sector peers, official classification, why-it's-here reasoning.
   Scrim click closes; clicks inside the panel don't. */
import { useEffect, useState } from 'react';
import { getStockDeepDive, type StockDeepDive } from '../v3/api';
import { isLowDelivery, isThinTrading } from '../v3/format';
import type { InfoV4Data } from './InfoV4';
import LogoV4 from './LogoV4';
import { useAuth } from '../lib/auth';

function fmtPct(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

export default function DeepDiveV4({
  ticker,
  alertId,
  onOpenPeer,
  onOpenInfo,
  onClose,
}: {
  ticker: string;
  alertId?: number;
  onOpenPeer: (ticker: string, alertId?: number) => void;
  onOpenInfo: (info: InfoV4Data) => void;
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
    <div className="ddscrim" onClick={onClose}>
      <div
        className="ddpop"
        role="dialog"
        aria-label={`Deep dive ${ticker}`}
        onClick={(event) => event.stopPropagation()}
      >
        <button className="bandclose" onClick={onClose}>
          Close ×
        </button>
        {error !== null && <p className="bandempty">{error}</p>}
        {data === null && error === null && (
          <div className="ddloading" aria-busy="true" aria-label="Loading">
            <span className="ddload-rule" />
            <p>Setting the type…</p>
            <span className="ddload-rule" />
          </div>
        )}
        {data !== null && (
          <>
            <div className="ddhead">
              <LogoV4 logoUrl={data.logo_url} ticker={data.ticker} name={data.name} size="md" />
              <div>
                <div className="ddname">{data.name}</div>
                <div className="ddmeta">
                  <span>{data.ticker}</span>
                  <span>{data.sector.replace(/_/g, ' ')}</span>
                  {data.cap_tier !== null && <span>{data.cap_tier} cap</span>}
                  {data.pe != null && <span>PE {data.pe.toFixed(1)}</span>}
                </div>
              </div>
            </div>

            <div className="sumline">
              {data.excess_move_pct !== null && (
                <span>
                  Excess
                  <b className={data.excess_move_pct < 0 ? 'down' : 'up'}>
                    {fmtPct(data.excess_move_pct)}
                  </b>
                </span>
              )}
              <span>
                Raw / sector
                <b>
                  {data.raw_move_pct != null ? data.raw_move_pct.toFixed(1) : '—'} /{' '}
                  {data.sector_move_pct != null ? data.sector_move_pct.toFixed(1) : '—'}
                </b>
              </span>
              <span>
                Volume
                <b>{data.volume_multiple != null ? `${data.volume_multiple.toFixed(1)}×` : '—'}</b>
              </span>
            </div>

            {data.intensity !== null && data.intensity.components.length > 0 && (
              <div className="layer4">
                <div className="lhead4">
                  <span className="li4" aria-hidden="true">
                    ◆
                  </span>
                  <span>
                    {data.intensity.band} intensity {data.intensity.score} — how the score is built
                  </span>
                </div>
                <div className="lbody4">
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
              </div>
            )}

            {warnings.map((warning) => (
              <p className="warnbox4" key={warning}>
                ⚠ {warning}
              </p>
            ))}

            {data.peers.length > 0 && (
              <div className="layer4">
                <div className="lhead4">
                  <span className="li4" aria-hidden="true">
                    ◆
                  </span>
                  <span>Sector peers — by intensity</span>
                </div>
                <div className="lbody4">
                  {data.peers.map((peer) => (
                    <div
                      className="crow"
                      key={peer.ticker}
                      onClick={() => onOpenPeer(peer.ticker, alertId)}
                      data-testid={`v4peer-${peer.ticker}`}
                    >
                      <LogoV4 logoUrl={peer.logo_url} ticker={peer.ticker} name={peer.name} />
                      <div className="cbody">
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
                      {/* (i) = glance and stay; the row itself hops the
                          deep dive to this peer. */}
                      <button
                        className="ib4"
                        aria-label={`About ${peer.ticker}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          onOpenInfo({
                            name: peer.name,
                            ticker: peer.ticker,
                            sector: peer.sector,
                            logoUrl: peer.logo_url,
                            fundamentals: peer.fundamentals,
                          });
                        }}
                      >
                        i
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {data.fundamentals && (
              <div className="layer4">
                <div className="lhead4">
                  <span className="li4" aria-hidden="true">
                    ◆
                  </span>
                  <span>What they do — {data.fundamentals.source}</span>
                </div>
                <div className="lbody4">
                  <p className="ddprose">
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
              </div>
            )}

            {(data.why !== null || data.rationale !== null) && (
              <div className="layer4">
                <div className="lhead4">
                  <span className="li4" aria-hidden="true">
                    ◆
                  </span>
                  <span>
                    {data.section_title !== null
                      ? `Why it's under "${data.section_title}"`
                      : 'Why it appears in this story'}
                  </span>
                </div>
                <div className="lbody4">
                  <ul className="ddwhy">
                    {data.why !== null && <li className="ddprose">{data.why}</li>}
                    {data.rationale !== null && data.rationale !== data.why && (
                      <li className="ddprose">{data.rationale}</li>
                    )}
                  </ul>
                </div>
              </div>
            )}

            <p className="dddisc">
              Intensity measures how hard the news hit this stock — not whether it's a good
              investment. Percentages are measured market moves, not forecasts.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
