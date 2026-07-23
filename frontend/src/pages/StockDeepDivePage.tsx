import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import IntensityBreakdownPopup from '../components/feed-v2/IntensityBreakdownPopup';
import PeerRow from '../components/feed-v2/PeerRow';
import BusinessPopup from '../components/feed-v2/BusinessPopup';
import AlertDetail from '../components/AlertDetail';
import { capTierColorClass, formatExcess } from '../lib/feedV2Format';
import { getStockDeepDive, type StockDeepDive } from '../lib/feedV2Api';
import { useAuth } from '../lib/auth';

export default function StockDeepDivePage() {
  const { ticker } = useParams<{ ticker: string }>();
  const [searchParams] = useSearchParams();
  const alertIdParam = searchParams.get('alertId');
  const alertId = alertIdParam !== null ? Number(alertIdParam) : undefined;
  const { token } = useAuth();

  const [deepDive, setDeepDive] = useState<StockDeepDive | null | undefined>(undefined);
  const [businessPopupTicker, setBusinessPopupTicker] = useState<string | null>(null);

  useEffect(() => {
    if (!ticker) return;
    let active = true;
    setDeepDive(undefined);
    getStockDeepDive(ticker, alertId, token)
      .then((data) => {
        if (active) setDeepDive(data);
      })
      .catch(() => {
        if (active) setDeepDive(null);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, alertId, token]);

  if (deepDive === undefined) return null;

  if (deepDive === null) {
    return (
      <main className="mx-auto w-full max-w-3xl px-4 py-8">
        <p className="font-sans text-sm text-muted">Stock not found.</p>
      </main>
    );
  }

  const hasAlertContext = deepDive.excess_move_pct !== null && deepDive.intensity !== null;
  const isExposureWithinAlert = deepDive.is_exposure_only === true;
  const popupPeer = deepDive.peers.find((p) => p.ticker === businessPopupTicker) ?? null;

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 py-8">
      <div className="rounded-lg bg-surface p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="font-sans text-lg text-ink">{deepDive.name}</span>
            {deepDive.cap_tier && (
              <span
                className={`rounded-full px-2 py-0.5 font-sans text-[11px] uppercase tracking-widest ${capTierColorClass(deepDive.cap_tier)}`}
              >
                {deepDive.cap_tier}
              </span>
            )}
            {deepDive.in_my_holdings && (
              <span className="h-[7px] w-[7px] shrink-0 rounded-full bg-accent" />
            )}
          </div>
          {hasAlertContext && deepDive.intensity && (
            <div className="flex items-baseline gap-2">
              <span className="font-data text-3xl font-medium text-ink">{deepDive.intensity.score}</span>
              <span className="font-sans text-sm text-muted">{deepDive.intensity.band}</span>
            </div>
          )}
          {isExposureWithinAlert && (
            <span className="font-sans text-sm text-muted">Exposure</span>
          )}
        </div>
        <p className="mt-1 font-sans text-xs uppercase tracking-widest text-muted">
          {deepDive.ticker} · {deepDive.sector}
        </p>
      </div>

      {hasAlertContext && (
        <div className="rounded-lg bg-surface p-5">
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Excess</div>
              <div className={`font-data text-lg ${(deepDive.excess_move_pct ?? 0) >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                {formatExcess(deepDive.excess_move_pct as number).text}
              </div>
            </div>
            <div>
              <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Raw / Sector</div>
              <div className="font-data text-lg text-ink">
                {deepDive.raw_move_pct?.toFixed(1)} / {deepDive.sector_move_pct?.toFixed(1)}
              </div>
            </div>
            <div>
              <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Volume</div>
              <div className="font-data text-lg text-ink">
                {deepDive.volume_multiple !== null ? `${deepDive.volume_multiple.toFixed(1)}×` : '—'}
              </div>
            </div>
          </div>
        </div>
      )}

      {hasAlertContext && deepDive.intensity && <IntensityBreakdownPopup intensity={deepDive.intensity} />}

      <div className="rounded-lg bg-surface p-5">
        <div className="font-sans text-[11px] uppercase tracking-widest text-muted">What they do</div>
        <p className="mt-2 font-sans text-sm text-ink">
          {deepDive.business_desc ?? 'Business description not available.'}
        </p>
        <div className="mt-4 flex gap-6">
          <div>
            <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Market cap</div>
            <div className="font-data text-sm text-ink">
              {deepDive.market_cap !== null ? deepDive.market_cap.toLocaleString() : '—'}
            </div>
          </div>
          <div>
            <div className="font-sans text-[11px] uppercase tracking-widest text-muted">P/E</div>
            <div className="font-data text-sm text-ink">{deepDive.pe !== null ? deepDive.pe.toFixed(1) : '—'}</div>
          </div>
        </div>
      </div>

      {deepDive.peers.length > 0 && (
        <div className="rounded-lg bg-surface p-5">
          <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Sector peers</div>
          <div className="mt-2 flex flex-col gap-1">
            {deepDive.peers.map((peer) => (
              <PeerRow
                key={peer.ticker}
                ticker={peer.ticker}
                capTier={peer.cap_tier}
                direction={peer.direction}
                excessMovePct={peer.excess_move_pct}
                intensity={peer.intensity}
                isExposureOnly={peer.is_exposure_only}
                inMyHoldings={peer.in_my_holdings}
                alertId={alertId}
                onOpenBusinessPopup={() => setBusinessPopupTicker(peer.ticker)}
              />
            ))}
          </div>
        </div>
      )}

      <AlertDetail open={popupPeer !== null} onClose={() => setBusinessPopupTicker(null)}>
        {popupPeer && (
          <BusinessPopup
            ticker={popupPeer.ticker}
            sector={popupPeer.sector}
            capTier={popupPeer.cap_tier}
            businessDesc={popupPeer.business_desc}
          />
        )}
      </AlertDetail>
    </main>
  );
}
