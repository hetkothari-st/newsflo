/* Bottom sheets (spec v2 §2 deeper levels, §7): the (i) glance popup and
   the stock deep-dive. The two are deliberately separate -- (i) = glance
   and stay, row = go deep. Ported from the prototype's openInfo/openDD. */
import { useEffect, useState } from 'react';
import {
  getStockDeepDive,
  type Intensity,
  type LayerRow,
  type StockDeepDive,
} from './api';
import CompanyLogo from './CompanyLogo';
import {
  bandClass,
  capClass,
  componentLabel,
  fmtPct,
  fmtVolume,
  isLowDelivery,
  isThinTrading,
  moveColor,
} from './format';
import Fundamentals from '../components/Fundamentals';
import type { Fundamentals as FundamentalsData } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';

export interface InfoSheetData {
  name: string;
  ticker: string;
  sector: string;
  // BSE-sourced classification + ratios, replacing the old LLM-invented
  // business_desc paragraph. Null when this company has no official BSE
  // classification -- renders no "What they do" section at all.
  fundamentals?: FundamentalsData | null;
  logoUrl: string | null;
}

export type SheetRequest =
  | { kind: 'info'; info: InfoSheetData }
  | { kind: 'deepDive'; ticker: string; alertId?: number };

export function InfoSheetContent({ info }: { info: InfoSheetData }) {
  return (
    <>
      <div className="ddh">
        <div>
          <div className="ddn">
            <CompanyLogo logoUrl={info.logoUrl} ticker={info.ticker} sector={info.sector} size="md" />
            {info.name}
          </div>
          <div className="dds">
            {info.ticker} · {info.sector}
          </div>
        </div>
      </div>
      {/* No fallback text: an unclassified company renders no section here
          at all -- Fundamentals itself returns null when data is null. */}
      {info.fundamentals && (
        <>
          <p className="seclab">What they do</p>
          <Fundamentals data={info.fundamentals} />
        </>
      )}
      <p className="disc">Glance view. Tap the row for the full impact breakdown.</p>
    </>
  );
}

function IntensityComponents({ intensity }: { intensity: Intensity }) {
  return (
    <>
      {intensity.components.map((component) => (
        <div className="comp" key={component.label}>
          <span className="cl">{componentLabel(component)}</span>
          <span className="cbar">
            <span
              className={`bar ${bandClass(component.score)}`}
              style={{ width: `${component.score}%` }}
            />
          </span>
          <span className="cw">
            {component.score} × {component.weight.toFixed(2).replace(/^0/, '')}
          </span>
        </div>
      ))}
    </>
  );
}

function PeerRow({ peer, onOpen }: { peer: LayerRow; onOpen: (ticker: string) => void }) {
  const score = peer.intensity?.score ?? null;
  return (
    <div className="peer" onClick={() => onOpen(peer.ticker)}>
      <CompanyLogo logoUrl={peer.logo_url} ticker={peer.ticker} sector={peer.sector} size="sm" />
      <span className="tkr">{peer.ticker}</span>
      <span className={`tag ${capClass(peer.cap_tier)}`}>{peer.cap_tier ?? '—'}</span>
      {score != null ? (
        <>
          <span className="bw" style={{ marginLeft: 'auto' }}>
            <span className={`bar ${bandClass(score)}`} style={{ width: `${score}%` }} />
          </span>
          <span className="sc">{score}</span>
        </>
      ) : (
        <span className="sc" style={{ marginLeft: 'auto' }}>
          —
        </span>
      )}
    </div>
  );
}

export function DeepDiveSheetContent({
  ticker,
  alertId,
  onOpenPeer,
}: {
  ticker: string;
  alertId?: number;
  onOpenPeer: (ticker: string) => void;
}) {
  const { token } = useAuth();
  const { language } = useLanguage();
  const [data, setData] = useState<StockDeepDive | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    getStockDeepDive(ticker, alertId, token, language)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker, alertId, token, language]);

  if (error) return <p className="empty">{error}</p>;
  if (data === null) return <p className="empty">Loading…</p>;

  const warnings: string[] = [];
  if (isLowDelivery(data.delivery_pct)) {
    warnings.push(
      `Only ${Math.round(data.delivery_pct!)}% of volume went to delivery — much of this move was intraday speculation, not accumulation.`,
    );
  }
  if (isThinTrading(data.liquidity_tier, data.cap_tier)) {
    warnings.push(
      'Small size and thin trading amplify moves both ways; exiting can be hard — higher risk.',
    );
  }

  const sectorLine = `${data.sector}${data.pe != null ? ` · PE ${data.pe.toFixed(1)}` : ' · PE —'}`;

  return (
    <>
      <div className="ddh">
        <div>
          <div className="ddn">
            <CompanyLogo logoUrl={data.logo_url} ticker={data.ticker} sector={data.sector} size="md" />
            {data.name} <span className={`tag ${capClass(data.cap_tier)}`}>{data.cap_tier ?? '—'}</span>
          </div>
          <div className="dds">
            {data.ticker} · {sectorLine}
          </div>
        </div>
        {data.intensity !== null && data.excess_move_pct !== null && (
          <div className="ddsc">
            <div className="n" style={{ color: moveColor(data.excess_move_pct) }}>
              {data.intensity.score}
            </div>
            <div className="b" style={{ color: moveColor(data.excess_move_pct) }}>
              {data.intensity.band} intensity
            </div>
          </div>
        )}
      </div>
      {data.excess_move_pct !== null && (
        <div className="tiles">
          <div className="tile">
            <div className="l">Excess</div>
            <div className="v" style={{ color: moveColor(data.excess_move_pct) }}>
              {fmtPct(data.excess_move_pct)}
            </div>
          </div>
          <div className="tile">
            <div className="l">Raw / sector</div>
            <div className="v" style={{ color: 'var(--ink2)' }}>
              {data.raw_move_pct != null ? data.raw_move_pct.toFixed(1) : '—'} /{' '}
              {data.sector_move_pct != null ? data.sector_move_pct.toFixed(1) : '—'}
            </div>
          </div>
          <div className="tile">
            <div className="l">Volume</div>
            <div className="v">{fmtVolume(data.volume_multiple)}</div>
          </div>
        </div>
      )}
      {data.intensity !== null && (
        <>
          <p className="seclab">How this score is built · {data.intensity.components.length} signals</p>
          <IntensityComponents intensity={data.intensity} />
        </>
      )}
      {warnings.length > 0 && (
        <div className="wbox">
          {warnings.map((warning, index) => (
            <span key={warning}>
              ⚠ {warning}
              {index < warnings.length - 1 && (
                <>
                  <br />
                  <br />
                </>
              )}
            </span>
          ))}
        </div>
      )}
      {data.peers.length > 0 && (
        <>
          <p className="seclab">Sector peers · by intensity</p>
          {data.peers.map((peer) => (
            <PeerRow key={peer.ticker} peer={peer} onOpen={onOpenPeer} />
          ))}
        </>
      )}
      {/* No fallback text: business_desc was LLM-invented and the backend
          now always sends null. An unclassified company renders nothing
          here -- Fundamentals itself returns null. */}
      {data.fundamentals && (
        <>
          <p className="seclab">What they do</p>
          <Fundamentals data={data.fundamentals} />
        </>
      )}
      {(data.why !== null || data.rationale !== null) && (
        <>
          <p className="seclab">
            {data.section_title !== null ? `Why it's under "${data.section_title}"` : 'Why it appears in this story'}
          </p>
          <ul className="whylist" data-testid="why-list">
            {data.why !== null && <li>{data.why}</li>}
            {data.rationale !== null && data.rationale !== data.why && <li>{data.rationale}</li>}
          </ul>
        </>
      )}
      <p className="disc">
        Intensity measures how hard the news hit this stock — not whether it's a good investment.
        Percentages are measured market moves, not forecasts.
      </p>
    </>
  );
}

export function SheetHost({
  request,
  onClose,
  onOpenPeer,
}: {
  request: SheetRequest | null;
  onClose: () => void;
  onOpenPeer: (ticker: string, alertId?: number) => void;
}) {
  return (
    <>
      <div className={`scrim ${request ? 'on' : ''}`} onClick={onClose} data-testid="scrim" />
      <div className={`sheet ${request ? 'on' : ''}`} data-testid="sheet">
        <div className="grab" />
        <div>
          {request?.kind === 'info' && <InfoSheetContent info={request.info} />}
          {request?.kind === 'deepDive' && (
            <DeepDiveSheetContent
              ticker={request.ticker}
              alertId={request.alertId}
              onOpenPeer={(ticker) => onOpenPeer(ticker, request.alertId)}
            />
          )}
        </div>
      </div>
    </>
  );
}
