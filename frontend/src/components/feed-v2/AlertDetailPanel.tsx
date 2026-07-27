import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatExcess, verdictLabel } from '../../lib/feedV2Format';
import type { FeedV2Alert } from '../../lib/feedV2Api';
import RippleSection from './RippleSection';
import TimelineSection from './TimelineSection';

type TabKey = 'affected' | 'ripple' | 'timeline';

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

interface AlertDetailPanelProps {
  alert: FeedV2Alert;
}

export default function AlertDetailPanel({ alert }: AlertDetailPanelProps) {
  const [activeTab, setActiveTab] = useState<TabKey | null>(null);
  const navigate = useNavigate();

  const impactCompanies = alert.impact_companies ?? [];
  const ripple = alert.ripple ?? [];
  const timeline = alert.timeline ?? [];

  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: 'affected', label: 'Affected', count: impactCompanies.length },
    { key: 'ripple', label: 'Ripple', count: ripple.length },
    { key: 'timeline', label: 'Timeline', count: timeline.length },
  ];

  function toggleTab(key: TabKey) {
    setActiveTab((current) => (current === key ? null : key));
  }

  return (
    <div className="flex flex-col gap-3">
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

      <div className="rounded-lg bg-surface">
        <div className="flex border-b border-hairline">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => toggleTab(tab.key)}
              className={`flex-1 border-b-2 px-3 py-3 font-sans text-xs uppercase tracking-widest ${
                activeTab === tab.key ? 'border-accent text-ink' : 'border-transparent text-muted'
              }`}
            >
              {tab.label} ({tab.count})
            </button>
          ))}
        </div>

        {activeTab === 'affected' && (
          <div className="p-5">
            {impactCompanies.length === 0 ? (
              <p className="font-sans text-sm text-muted">No affected companies found.</p>
            ) : (
              <div className="flex flex-col gap-4">
                {impactCompanies.map((company) => (
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
            )}
          </div>
        )}

        {activeTab === 'ripple' &&
          (ripple.length === 0 ? (
            <p className="p-5 font-sans text-sm text-muted">No ripple detected.</p>
          ) : (
            <RippleSection companies={ripple} alertId={alert.id} />
          ))}

        {activeTab === 'timeline' &&
          (timeline.length === 0 ? (
            <p className="p-5 font-sans text-sm text-muted">No timeline available.</p>
          ) : (
            <TimelineSection entries={timeline} />
          ))}
      </div>
    </div>
  );
}
