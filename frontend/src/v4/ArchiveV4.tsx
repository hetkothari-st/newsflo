/* v4 archive -- the broadsheet's back-issues page (the v3 calendar
   mechanism restyled): a month of days set as plain numerals, days with
   measured stories in ink and clickable, empty days in pebble. Picking
   a day reopens that edition on the front page. */
import { useEffect, useState } from 'react';
import { getCalendarCounts, type CalendarCounts } from '../v3/api';

const MONTH_TITLE = new Intl.DateTimeFormat('en-IN', { month: 'long', year: 'numeric' });
const WEEKDAYS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

interface PulseDay {
  date: string;
  count: number;
}

const PULSE_DAY = new Intl.DateTimeFormat('en-IN', {
  weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata',
});

export default function ArchiveV4({
  onPick,
  onPickPulse,
}: {
  onPick: (date: string) => void;
  onPickPulse?: (date: string) => void;
}) {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1); // 1-based
  const [counts, setCounts] = useState<CalendarCounts | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The pulse wire's own back days (IST) -- independent of the alert
  // calendar above; the wire has items on days with no measured stories.
  const [pulseDays, setPulseDays] = useState<PulseDay[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/pulse-live/dates')
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((days: PulseDay[]) => {
        if (!cancelled) setPulseDays(days);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setCounts(null);
    setError(null);
    getCalendarCounts(year, month)
      .then((result) => {
        if (!cancelled) setCounts(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [year, month]);

  const step = (delta: number) => {
    let nextMonth = month + delta;
    let nextYear = year;
    if (nextMonth === 0) {
      nextMonth = 12;
      nextYear -= 1;
    } else if (nextMonth === 13) {
      nextMonth = 1;
      nextYear += 1;
    }
    setMonth(nextMonth);
    setYear(nextYear);
  };

  const daysInMonth = new Date(year, month, 0).getDate();
  // Monday-first column offset for the 1st of the month.
  const firstOffset = (new Date(year, month - 1, 1).getDay() + 6) % 7;
  const iso = (day: number) => `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;

  return (
    <div className="page4">
      <h1 className="phead">The archive</h1>
      <p className="psub">Every past edition, by date. Days set in ink carry measured stories.</p>
      <div className="texttabs">
        <button onClick={() => step(-1)} aria-label="Previous month">
          ← Earlier
        </button>
        <span className="archmonth">{MONTH_TITLE.format(new Date(year, month - 1, 1))}</span>
        <button onClick={() => step(1)} aria-label="Next month">
          Later →
        </button>
      </div>
      {error !== null && <p className="empty4">{error}</p>}
      {counts !== null && (
        <div className="archgrid" role="grid" aria-label="Editions by date">
          {WEEKDAYS.map((weekday, index) => (
            <span className="archwd" key={`${weekday}-${index}`}>
              {weekday}
            </span>
          ))}
          {Array.from({ length: firstOffset }, (_, index) => (
            <span key={`pad-${index}`} />
          ))}
          {Array.from({ length: daysInMonth }, (_, index) => {
            const day = index + 1;
            const date = iso(day);
            const hasStories = (counts[date] ?? 0) > 0;
            return hasStories ? (
              <button
                key={date}
                className="archday on"
                onClick={() => onPick(date)}
                aria-label={`Open the ${date} edition`}
              >
                {day}
              </button>
            ) : (
              <span key={date} className="archday">
                {day}
              </span>
            );
          })}
        </div>
      )}
      {onPickPulse && pulseDays.length > 0 && (
        <>
          <h2 className="archsub">The pulse wire</h2>
          <p className="psub">Raw wire days, unanalysed. Latest day lives on the Pulse tab.</p>
          <div className="pulsedays">
            {pulseDays.map((day) => (
              <button
                key={day.date}
                className="pulseday"
                onClick={() => onPickPulse(day.date)}
                aria-label={`Open the ${day.date} pulse wire`}
              >
                <span>{PULSE_DAY.format(new Date(`${day.date}T12:00:00`))}</span>
                <b>{day.count}</b>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
