import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getAlert, type Alert } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
import { useHorizontalSwipe } from '../lib/useHorizontalSwipe';
import SectorTreemap from '../features/visualize/charts/SectorTreemap';
import TierRows from '../features/visualize/charts/TierRows';
import ImpactBar from '../features/visualize/charts/ImpactBar';
import SplitDonut from '../features/visualize/charts/SplitDonut';

const CHARTS = [
  { key: 'sector', label: 'Sector', Component: SectorTreemap },
  { key: 'tier', label: 'Tier', Component: TierRows },
  { key: 'impact', label: 'Impact', Component: ImpactBar },
  { key: 'split', label: 'Split', Component: SplitDonut },
] as const;

export default function AlertChartsPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { token } = useAuth();
  const { language } = useLanguage();
  const [alert, setAlert] = useState<Alert | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);

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

  return (
    <div className="flex min-h-screen flex-col bg-page" {...swipeHandlers}>
      <div className="flex items-center gap-3 border-b border-hairline p-4">
        <button type="button" onClick={() => navigate(-1)} aria-label="Back" className="text-muted hover:text-ink">
          ←
        </button>
        <h1 className="truncate text-sm text-ink">{alert.article.title}</h1>
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
        <Component companies={alert.companies} />
      </div>
    </div>
  );
}
