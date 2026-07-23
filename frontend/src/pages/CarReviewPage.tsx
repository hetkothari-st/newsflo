import { useEffect, useState } from 'react';
import {
  getCarReview, getCarReviewSummary,
  type CarOutcomeLabel, type CarReviewRow, type CarReviewSummary,
} from '../lib/carReviewApi';
import { useAuth } from '../lib/auth';

function labelColorClass(label: CarOutcomeLabel): string {
  if (label === 'HELD') return 'text-bullish';
  if (label === 'REVERSED') return 'text-bearish';
  return 'text-muted';
}

export default function CarReviewPage() {
  const { token } = useAuth();
  const [rows, setRows] = useState<CarReviewRow[] | null>(null);
  const [summary, setSummary] = useState<CarReviewSummary | null>(null);

  useEffect(() => {
    let active = true;
    getCarReview(token)
      .then((data) => {
        if (active) setRows(data);
      })
      .catch(() => {
        if (active) setRows([]);
      });
    getCarReviewSummary(token)
      .then((data) => {
        if (active) setSummary(data);
      })
      .catch(() => {
        if (active) setSummary(null);
      });
    return () => {
      active = false;
    };
  }, [token]);

  if (rows === null) return null;

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 py-8">
      {summary && summary.hold_rate !== null && summary.mean_car_pct !== null && (
        <div className="rounded-lg bg-surface p-5">
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Sample count</div>
              <div className="font-data text-lg text-ink">{summary.sample_count}</div>
            </div>
            <div>
              <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Hold rate</div>
              <div className="font-data text-lg text-ink">{Math.round(summary.hold_rate * 100)}%</div>
            </div>
            <div>
              <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Mean CAR</div>
              <div className="font-data text-lg text-ink">{summary.mean_car_pct.toFixed(1)}%</div>
            </div>
          </div>
        </div>
      )}

      <div className="rounded-lg bg-surface p-5">
        {rows.length === 0 ? (
          <p className="font-sans text-sm text-muted">No outcomes yet.</p>
        ) : (
          <div className="flex flex-col divide-y divide-hairline">
            {rows.map((row) => (
              <div key={row.id} className="flex flex-col gap-1 py-3">
                <div className="flex items-center gap-2">
                  <span className="font-sans text-sm text-ink">{row.company_name}</span>
                  <span className="font-data text-[11px] text-muted">{row.ticker}</span>
                  <span className="font-sans text-xs uppercase tracking-widest text-muted">{row.category}</span>
                  <span className={`ml-auto font-sans text-xs uppercase tracking-widest ${labelColorClass(row.outcome_label)}`}>
                    {row.outcome_label}
                  </span>
                </div>
                <a
                  href={row.article_url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-sans text-sm text-ink underline"
                >
                  {row.article_title}
                </a>
                <div className="flex gap-6 font-data text-xs text-muted">
                  <span>Day 0: {row.day0_excess_move_pct.toFixed(1)}%</span>
                  <span>CAR (-1..+3d): {row.car_pct.toFixed(1)}%</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
