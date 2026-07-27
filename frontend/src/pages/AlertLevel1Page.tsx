import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { formatExcess, verdictLabel } from '../lib/feedV2Format';
import { getFeedV2Alert, type FeedV2Alert } from '../lib/feedV2Api';
import { useAuth } from '../lib/auth';

function signedPct(value: number): string {
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}%`;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function AlertLevel1Page() {
  const { id } = useParams<{ id: string }>();
  const alertId = id !== undefined ? Number(id) : undefined;
  const { token } = useAuth();
  const navigate = useNavigate();

  const [alert, setAlert] = useState<FeedV2Alert | null | undefined>(undefined);

  useEffect(() => {
    if (alertId === undefined) return;
    let active = true;
    setAlert(undefined);
    getFeedV2Alert(alertId, token)
      .then((data) => {
        if (active) setAlert(data);
      })
      .catch(() => {
        if (active) setAlert(null);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alertId, token]);

  if (alert === undefined) return null;

  if (alert === null) {
    return (
      <main className="mx-auto w-full max-w-3xl px-4 py-8">
        <p className="font-sans text-sm text-muted">Alert not found.</p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 py-8">
      <Link to="/feed-v2" className="font-sans text-xs text-muted underline">
        ← Feed
      </Link>

      <div className="rounded-lg bg-surface p-5">
        <span className="rounded-full bg-elevated px-2 py-0.5 text-[11px] uppercase tracking-widest text-muted">
          {verdictLabel(alert.verdict)}
        </span>
        {alert.summary_long && (
          <p className="mt-3 font-sans text-sm text-ink">{alert.summary_long}</p>
        )}
      </div>

      <div className="rounded-lg bg-surface p-5">
        <div className="flex gap-6">
          <div>
            <div className="font-sans text-xs text-muted">Raw move</div>
            <div
              className={`font-data text-lg font-medium ${
                alert.raw_move_pct >= 0 ? 'text-bullish' : 'text-bearish'
              }`}
            >
              {signedPct(alert.raw_move_pct)}
            </div>
          </div>
          <div>
            <div className="font-sans text-xs text-muted">Sector move</div>
            <div className="font-data text-lg font-medium text-muted">{signedPct(alert.sector_move_pct)}</div>
          </div>
        </div>
        {alert.volume_multiple !== null && (
          <div className="mt-3 font-data text-sm text-ink">
            {alert.volume_multiple.toFixed(1)}× average volume
          </div>
        )}
      </div>

      <div className="rounded-lg bg-surface p-5">
        <div className="font-sans text-xs text-muted">
          {alert.article.source} &middot; {alert.is_fallback_benchmark ? 'vs Nifty 50' : 'vs sector index'}
        </div>
        <time className="mt-1 block font-sans text-xs text-muted" dateTime={alert.created_at}>
          {formatTime(alert.created_at)}
        </time>
      </div>

      {alert.impact_companies && alert.impact_companies.length > 0 && (
        <div className="rounded-lg bg-surface p-5">
          <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Affected companies</div>
          <div className="mt-3 flex flex-col gap-4">
            {alert.impact_companies.map((company) => (
              <div
                key={company.ticker}
                role="button"
                tabIndex={0}
                aria-label={company.ticker}
                onClick={() => navigate(`/feed-v2/stock/${company.ticker}?alertId=${alert.id}`)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    navigate(`/feed-v2/stock/${company.ticker}?alertId=${alert.id}`);
                  }
                }}
                className="cursor-pointer"
              >
                <div className="flex items-center gap-3">
                  <span className="font-data text-[11px] text-muted">{company.ticker}</span>
                  <span
                    className={`font-data text-xs ${
                      company.direction === 'bullish' ? 'text-bullish' : 'text-bearish'
                    }`}
                  >
                    {formatExcess(company.excess_move_pct).text}
                  </span>
                </div>
                {company.why && <p className="mt-1 font-sans text-[13px] text-ink">{company.why}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      <Link to={`/feed-v2/alert/${alert.id}/ripple`} className="self-end font-sans text-xs text-muted underline">
        See ripple →
      </Link>
    </main>
  );
}
