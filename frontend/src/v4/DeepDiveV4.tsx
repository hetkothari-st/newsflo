/* v4 deep dive -- a paper popup over the current page, in exactly the
   ripple page's visual language: serif name, ruled stats strip, ink
   section strips, ledger peer rows. Functional parity with the deployed
   deep-dive sheet: measured numbers, intensity build-up, risk warnings,
   sector peers, official classification, why-it's-here reasoning.
   Scrim click closes; clicks inside the panel don't. */
import { useEffect, useState } from 'react';
import { getStockDeepDive, type StockDeepDive } from '../v3/api';
import { componentLabel, isLowDelivery, isThinTrading } from '../v3/format';
import type { InfoV4Data } from './InfoV4';
import LogoV4 from './LogoV4';
import VolRangeV4 from './VolRangeV4';
import { useAuth } from '../lib/auth';

function fmtPct(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

// Frontend mirror of app.market.measure.MARKET_REACTION_DEAD_ZONE_PCT --
// only used as a fallback for rows that carry no server-classified
// reaction_direction (StockDeepDive's own excess number today has none).
// Keeps a near-zero/0.0 excess from ever rendering green off a bare sign
// check (spec §39).
const REACTION_DEAD_ZONE_PCT = 0.25;

/* Dead-zone-aware reaction class: the server's reaction_direction is the
   single semantic source when present (spec §37); only when it is absent
   does this fall back to the same dead zone classify_reaction applies --
   never a bare `< 0` sign check. */
function reactionCls(excess: number, direction?: string | null): string {
  if (direction === 'positive') return 'up';
  if (direction === 'negative') return 'down';
  if (direction === 'flat' || direction === 'unknown') return 'flat';
  if (Math.abs(excess) < REACTION_DEAD_ZONE_PCT) return 'flat';
  return excess < 0 ? 'down' : 'up';
}

/* First two sentences of the sourced description -- the deep dive wants
   a compact "who is this" line, not the full sourced paragraph (that
   stays in the (i) glance). Attribution link still travels with it. */
function shortDesc(text: string): string {
  const sentences = text.match(/[^.!?]+[.!?]+(?:\s|$)/g);
  if (!sentences || sentences.length <= 2) return text;
  return sentences.slice(0, 2).join('').trim();
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
            <p>Loading…</p>
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

            {/* Measured numbers only -- a cell with nothing measured is
                omitted, never rendered as an em-dash wall (the null "— / —"
                strip read as broken). No numbers, no strip. */}
            {(data.excess_move_pct !== null ||
              data.raw_move_pct != null ||
              data.volume_multiple != null) && (
              <div className="sumline">
                {data.excess_move_pct !== null && (
                  <span>
                    Excess
                    <b className={reactionCls(data.excess_move_pct)}>
                      {fmtPct(data.excess_move_pct)}
                    </b>
                  </span>
                )}
                {(data.raw_move_pct != null || data.sector_move_pct != null) && (
                  <span>
                    Raw / sector
                    <b>
                      {data.raw_move_pct != null ? data.raw_move_pct.toFixed(1) : '—'} /{' '}
                      {data.sector_move_pct != null ? data.sector_move_pct.toFixed(1) : '—'}
                    </b>
                  </span>
                )}
                {data.volume_multiple != null && (
                  <span>
                    Volume
                    <b>{`${data.volume_multiple.toFixed(1)}×`}</b>
                  </span>
                )}
              </div>
            )}

            {data.volatility_range && (
              <div className="layer4">
                <div className="lhead4">
                  <span className="li4" aria-hidden="true">
                    ◆
                  </span>
                  <span>Typical on this news type</span>
                </div>
                <div className="lbody4">
                  <VolRangeV4 range={data.volatility_range} move={data.excess_move_pct} />
                </div>
              </div>
            )}

            {data.intensity !== null && data.intensity.components.length > 0 && (
              <div className="layer4">
                <div className="lhead4">
                  <span className="li4" aria-hidden="true">
                    ◆
                  </span>
                  <span>
                    {data.intensity.band} intensity {data.intensity.score} — how the score is built ·{' '}
                    {data.intensity.components.length} signals
                  </span>
                </div>
                <div className="lbody4">
                  {data.intensity.components.map((component) => (
                    <div className="comp4" key={component.label}>
                      <span className="cl">{componentLabel(component)}</span>
                      <span className="cbar">
                        <i style={{ width: `${Math.min(100, Math.max(0, component.score))}%` }} />
                      </span>
                      <span className="cv">
                        {component.score} × {component.weight.toFixed(2).replace(/^0/, '')}
                      </span>
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
                            <span className={`mv4 ${reactionCls(peer.excess_move_pct, peer.reaction_direction)}`}>
                              {fmtPct(peer.excess_move_pct)}
                            </span>
                          )}
                        </div>
                        <div className="cmeta">
                          <span>{peer.ticker}</span>
                          {peer.cap_tier !== null && <span>{peer.cap_tier} cap</span>}
                          {peer.confidence_band && (
                            /* Band-only confidence (final-blueprint §18/§19,
                               ruling R4, Task 9) -- never a numeric score. */
                            <span className="cband4" title={`Confidence: ${peer.confidence_band}`}>
                              {peer.confidence_band}
                            </span>
                          )}
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
                            businessDesc: peer.business_desc,
                            businessDescSourceUrl: peer.business_desc_source_url,
                            volatilityRange: peer.volatility_range,
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

            {/* Sourced description first (companies DB, CC BY-SA link
                travels with the text); the official classification is the
                deployed version's no-description fallback -- never any
                invented filler. */}
            {(data.fundamentals || data.business_desc) && (
              <div className="layer4">
                <div className="lhead4">
                  <span className="li4" aria-hidden="true">
                    ◆
                  </span>
                  <span>What they do{data.fundamentals ? ` — ${data.fundamentals.source}` : ''}</span>
                </div>
                <div className="lbody4">
                  {data.business_desc && (
                    <p className="ddprose">
                      {shortDesc(data.business_desc)}
                      {data.business_desc_source_url && (
                        <>
                          {' '}
                          <a
                            className="ddsource"
                            href={data.business_desc_source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            source
                          </a>
                        </>
                      )}
                    </p>
                  )}
                  {data.fundamentals && (
                    <p className="ddprose ddclass">
                      {[
                        data.fundamentals.classification.sector,
                        data.fundamentals.classification.industry,
                        data.fundamentals.classification.group,
                        data.fundamentals.classification.sub_group,
                      ]
                        .filter(Boolean)
                        .join(' — ')}
                    </p>
                  )}
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
