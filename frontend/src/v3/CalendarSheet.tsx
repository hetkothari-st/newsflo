/* Calendar (restored mechanism): pick any past date and reopen that day's
   feed -- per-day alert counts from /api/calendar/counts, IST day
   bucketing like the backend. Rendered inside the shell's bottom sheet. */
import { useEffect, useState } from 'react';
import { getCalendarCounts, type CalendarCounts } from './api';
import { useLanguage } from '../lib/language';

function todayIst(): { year: number; month: number; day: number } {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date());
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  return { year: get('year'), month: get('month'), day: get('day') };
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

const WEEKDAYS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export default function CalendarSheet({ onSelectDate }: { onSelectDate: (date: string | null) => void }) {
  const { t } = useLanguage();
  const [today] = useState(todayIst);
  const [cursor, setCursor] = useState({ year: today.year, month: today.month });
  const [counts, setCounts] = useState<CalendarCounts>({});

  useEffect(() => {
    let cancelled = false;
    getCalendarCounts(cursor.year, cursor.month)
      .then((result) => {
        if (!cancelled) setCounts(result);
      })
      .catch(() => {
        /* counts stay empty; days still selectable */
      });
    return () => {
      cancelled = true;
    };
  }, [cursor]);

  const daysInMonth = new Date(cursor.year, cursor.month, 0).getDate();
  const firstWeekday = new Date(cursor.year, cursor.month - 1, 1).getDay();
  const isCurrentMonth = cursor.year === today.year && cursor.month === today.month;

  const prevMonth = () =>
    setCursor(({ year, month }) => (month === 1 ? { year: year - 1, month: 12 } : { year, month: month - 1 }));
  const nextMonth = () =>
    setCursor(({ year, month }) => (month === 12 ? { year: year + 1, month: 1 } : { year, month: month + 1 }));

  return (
    <div data-testid="calendar-sheet">
      <div className="ddh">
        <div className="ddn">{t('v3.calendarTitle')}</div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontFamily: 'var(--mono)', fontSize: 12 }}>
          <button className="bx" aria-label="Previous month" onClick={prevMonth}>
            ‹
          </button>
          <span>
            {MONTH_LABELS[cursor.month - 1]} {cursor.year}
          </span>
          <button className="bx" aria-label="Next month" onClick={nextMonth} disabled={isCurrentMonth}>
            ›
          </button>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 4, textAlign: 'center' }}>
        {WEEKDAYS.map((label, index) => (
          <div key={index} style={{ fontSize: 9, color: 'var(--ink3)', fontFamily: 'var(--mono)' }}>
            {label}
          </div>
        ))}
        {Array.from({ length: firstWeekday }, (_, index) => (
          <div key={`pad-${index}`} />
        ))}
        {Array.from({ length: daysInMonth }, (_, index) => {
          const day = index + 1;
          const key = `${cursor.year}-${pad2(cursor.month)}-${pad2(day)}`;
          const count = counts[key] ?? 0;
          const isFuture =
            isCurrentMonth && day > today.day;
          const isToday = isCurrentMonth && day === today.day;
          return (
            <button
              key={key}
              disabled={isFuture}
              onClick={() => onSelectDate(isToday ? null : key)}
              style={{
                font: 'inherit', fontSize: 12, padding: '7px 0', borderRadius: 8, cursor: 'pointer',
                background: isToday ? 'var(--s2)' : 'transparent',
                color: isFuture ? 'var(--ink3)' : 'var(--ink)',
                border: '0.5px solid var(--border)', opacity: isFuture ? 0.4 : 1,
                position: 'relative',
              }}
            >
              {day}
              {count > 0 && (
                <span
                  style={{
                    position: 'absolute', bottom: 2, left: '50%', transform: 'translateX(-50%)',
                    width: 4, height: 4, borderRadius: '50%', background: 'var(--accent)',
                  }}
                />
              )}
            </button>
          );
        })}
      </div>
      <p className="disc">IST</p>
    </div>
  );
}
