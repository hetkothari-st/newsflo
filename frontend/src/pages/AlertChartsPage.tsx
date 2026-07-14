import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getAlert, type Alert } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
import { useHorizontalSwipe } from '../lib/useHorizontalSwipe';
import SectorTree from '../features/visualize/charts/SectorTree';
import TierRows from '../features/visualize/charts/TierRows';
import ImpactBar from '../features/visualize/charts/ImpactBar';
import SplitTree from '../features/visualize/charts/SplitTree';
import ConfidenceTree from '../features/visualize/charts/ConfidenceTree';
import TimelineTree from '../features/visualize/charts/TimelineTree';

const CHARTS = [
  { key: 'sector', label: 'Sector', Component: SectorTree },
  { key: 'tier', label: 'Tier', Component: TierRows },
  { key: 'impact', label: 'Impact', Component: ImpactBar },
  { key: 'split', label: 'Split', Component: SplitTree },
  { key: 'confidence', label: 'Confidence', Component: ConfidenceTree },
  { key: 'timeline', label: 'Timeline', Component: TimelineTree },
] as const;

type Breadth = 'normal' | 'drilldown';

export default function AlertChartsPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { token } = useAuth();
  const { language } = useLanguage();
  const [alert, setAlert] = useState<Alert | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [breadth, setBreadth] = useState<Breadth>('normal');

  useEffect(() => {
    if (!id) return;
    let active = true;
    getAlert(Number(id), token, language)
      .then((data) => {
        if (active) setAlert(data);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'Failed to load alert.');
      });
    return () => {
      active = false;
    };
  }, [id, token, language]);

  const swipeHandlers = useHorizontalSwipe({
    onSwipeLeft: () => setIndex((i) => Math.min(i + 1, CHARTS.length - 1)),
    onSwipeRight: () => (index === 0 ? navigate(-1) : setIndex((i) => Math.max(i - 1, 0))),
  });

  if (error) {
    return <p className="p-4 text-xs uppercase tracking-widest text-bearish">{error}</p>;
  }
  if (!alert) {
    return <p className="p-4 text-xs uppercase tracking-widest text-muted">Loading…</p>;
  }

  const { Component } = CHARTS[index];
  const visibleCompanies =
    breadth === 'normal' ? alert.companies.filter((c) => c.basis === 'direct_mention') : alert.companies;

  return (
    <div className="flex min-h-screen flex-col bg-page" {...swipeHandlers}>
      <div className="flex items-center gap-3 border-b border-hairline p-4">
        <button type="button" onClick={() => navigate(-1)} aria-label="Back" className="text-muted hover:text-ink">
          ←
        </button>
        <h1 className="truncate text-sm text-ink">{alert.article.title}</h1>
        <div className="ml-auto flex gap-1 self-start rounded-md border border-hairline bg-surface p-0.5">
          {(['normal', 'drilldown'] as Breadth[]).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setBreadth(mode)}
              className={`rounded px-2 py-0.5 text-[11px] uppercase tracking-widest ${
                breadth === mode ? 'bg-page text-ink' : 'text-muted'
              }`}
            >
              {mode === 'normal' ? 'Normal' : 'Drilldown'}
            </button>
          ))}
        </div>
      </div>
      <div className="flex gap-4 border-b border-hairline px-4 py-2">
        {CHARTS.map((chart, i) => (
          <button
            key={chart.key}
            type="button"
            onClick={() => setIndex(i)}
            className={`text-xs uppercase tracking-widest ${i === index ? 'text-ink' : 'text-muted'}`}
          >
            {chart.label}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto">
        {visibleCompanies.length === 0 ? (
          <p className="p-4 text-xs uppercase tracking-widest text-muted">
            No directly-confirmed companies for this alert — try Drilldown for the wider sector picture.
          </p>
        ) : (
          <Component companies={visibleCompanies} />
        )}
      </div>
    </div>
  );
}
