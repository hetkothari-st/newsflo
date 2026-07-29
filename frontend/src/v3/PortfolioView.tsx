/* Portfolio overlay (spec v2 §2, §8): the user's holdings and which of
   today's news touches them. Requires login -- holdings are sensitive
   (spec §9, DPDP). */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getPortfolioOverlay, type PortfolioOverlay } from './api';
import { useAuth } from '../lib/auth';

export default function PortfolioView({
  active,
  onOpenDeepDive,
}: {
  active: boolean;
  onOpenDeepDive: (ticker: string, alertId?: number) => void;
}) {
  const { token } = useAuth();
  const [overlay, setOverlay] = useState<PortfolioOverlay | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active || !token) return;
    let cancelled = false;
    getPortfolioOverlay(token)
      .then((result) => {
        if (!cancelled) setOverlay(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [active, token]);

  return (
    <div className={`view ${active ? 'on' : ''}`}>
      <div className="pagehd">
        <h2>Portfolio</h2>
        <p>Your holdings, and which of today's news touches them.</p>
      </div>
      {!token && (
        <p className="empty">
          <Link to="/login">Sign in</Link> to see which of today's news touches your holdings.
        </p>
      )}
      {error !== null && <p className="empty">{error}</p>}
      {token && overlay !== null && (
        <>
          <div className="pf-sum">
            <div className="lab">Holdings affected by today's news</div>
            <div style={{ fontFamily: 'var(--mono)', fontSize: 26, marginTop: 4 }}>
              {overlay.affected_count}
              <span style={{ fontSize: 14, color: 'var(--ink3)' }}> / {overlay.holdings.length}</span>
            </div>
          </div>
          {overlay.holdings.length === 0 && (
            <p className="empty">
              No holdings yet. <Link to="/holdings">Add your holdings</Link> to light up the
              portfolio thread across the feed.
            </p>
          )}
          {overlay.holdings.map((holding) => (
            <div
              className="pf-hold"
              key={holding.ticker}
              onClick={() => onOpenDeepDive(holding.ticker, holding.affected_alert_id ?? undefined)}
            >
              <span className="odot" />
              <div>
                <div className="de-name">{holding.name}</div>
                <div className="de-tk">
                  {holding.ticker} · {holding.quantity} sh
                </div>
              </div>
              {holding.affected_headline ? (
                <span className="pf-affected">{holding.affected_headline}</span>
              ) : (
                <span className="de-tk" style={{ marginLeft: 'auto' }}>
                  no news today
                </span>
              )}
            </div>
          ))}
        </>
      )}
      <p className="aa-note">
        Holdings sync each morning via Account Aggregator (Sahamati) consent — never PAN scraping.
        Encrypted at rest and in transit.
      </p>
    </div>
  );
}
