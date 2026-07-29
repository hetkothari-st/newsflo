/* Reaction review (spec v2 §4.7): did a flagged reaction hold or
   reverse? Cumulative abnormal return over trading days -1..+3, drawn as
   a per-day bar track. Back-validates intensity weights -- not a
   recommendation. */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCarReview, type CarReviewRow } from './api';
import { fmtPct } from './format';
import { useAuth } from '../lib/auth';

const DAY_LABELS = ['−1', '0', '+1', '+2', '+3'];

const OUTCOME_LABELS: Record<CarReviewRow['outcome_label'], { text: string; className: string }> = {
  HELD: { text: 'Held', className: 'held' },
  REVERSED: { text: 'Faded', className: 'fade' },
  FLAT: { text: 'Flat', className: 'flat' },
};

function CarCard({ row }: { row: CarReviewRow }) {
  const outcome = OUTCOME_LABELS[row.outcome_label];
  const series = row.car_series;
  const max = series ? Math.max(...series.map((value) => Math.abs(value)), 0.001) : null;
  return (
    <div className="car">
      <div className="car-top">
        <div className="car-hl">
          {row.article_title}
          <span style={{ color: 'var(--ink3)' }}> · {row.ticker}</span>
        </div>
        <span className={`car-verd ${outcome.className}`}>{outcome.text}</span>
      </div>
      {series !== null && max !== null && (
        <>
          <div className="car-track">
            {series.map((value, index) => (
              <div
                key={index}
                style={{
                  flex: 1,
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: value >= 0 ? 'flex-end' : 'flex-start',
                  height: '100%',
                }}
              >
                <div
                  className="car-bar"
                  style={{
                    height: `${(Math.abs(value) / max) * 100}%`,
                    background: value >= 0 ? 'var(--up)' : 'var(--down)',
                  }}
                />
              </div>
            ))}
          </div>
          <div className="car-lbl">
            {DAY_LABELS.slice(0, series.length).map((label) => (
              <span key={label}>{label}</span>
            ))}
          </div>
        </>
      )}
      <div
        style={{
          fontFamily: 'var(--mono)',
          fontSize: 11,
          marginTop: 8,
          color: row.car_pct >= 0 ? 'var(--up)' : 'var(--down)',
        }}
      >
        CAR {fmtPct(row.car_pct)}
      </div>
    </div>
  );
}

export default function ReviewView({ active }: { active: boolean }) {
  const { token } = useAuth();
  const [rows, setRows] = useState<CarReviewRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active || !token) return;
    let cancelled = false;
    getCarReview(token)
      .then((result) => {
        if (!cancelled) setRows(result);
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
        <h2>Reaction review</h2>
        <p>Did a flagged reaction hold or reverse? Cumulative abnormal return, −1 to +3 days.</p>
      </div>
      {!token && (
        <p className="empty">
          <Link to="/login">Sign in</Link> to review how flagged reactions played out.
        </p>
      )}
      {error !== null && <p className="empty">{error}</p>}
      {token && rows !== null && rows.length === 0 && (
        <p className="empty">No completed reaction windows yet — outcomes appear a few trading days after each alert.</p>
      )}
      {token && rows?.map((row) => <CarCard key={row.id} row={row} />)}
      <p className="aa-note">Used to back-validate intensity weights — not a recommendation.</p>
    </div>
  );
}
