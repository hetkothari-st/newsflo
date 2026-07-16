import { useEffect, useMemo, useState } from 'react';
import { getCalendarCounts, getCalendarDay, type Alert, type CalendarCounts } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
import AlertCompanies from './AlertCompanies';
import AlertCoverCard from './AlertCoverCard';
import AlertDetail from './AlertDetail';

// Calendar days are always bucketed by IST (see backend/app/routers/calendar.py),
// regardless of the viewer's browser timezone -- the app is India-focused and
// this keeps "today"/day boundaries aligned with the Indian trading day.
function todayIst(): { year: number; month: number; day: number } {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  return { year: get('year'), month: get('month'), day: get('day') };
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

function dateKey(year: number, month: number, day: number): string {
  return `${year}-${pad2(month)}-${pad2(day)}`;
}

function daysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

// Calendar-date weekday math is timezone-agnostic (a Gregorian date's weekday
// never depends on an instant/timezone) -- constructing a local midnight Date
// purely for `.getDay()` is safe regardless of the viewer's own timezone.
function firstWeekday(year: number, month: number): number {
  return new Date(year, month - 1, 1).getDay();
}

const WEEKDAY_LABELS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
const SELECT_CLASS =
  'rounded-md border border-hairline bg-surface px-1.5 py-0.5 text-xs text-ink theme-light:border-transparent theme-light:shadow-neu-sm';

export default function CalendarModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { token } = useAuth();
  const { language, t } = useLanguage();
  // Recomputed (not memoized-once) every time the modal opens -- CalendarModal
  // is mounted for the whole page lifetime (AlertDetail just returns null
  // while closed), so a plain one-time useMemo would freeze "today" at first
  // mount and go stale across an IST midnight rollover in a long-lived tab.
  const [today, setToday] = useState(todayIst);
  const [cursor, setCursor] = useState({ year: today.year, month: today.month });
  const [counts, setCounts] = useState<CalendarCounts>({});
  const [countsLoading, setCountsLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [dayAlerts, setDayAlerts] = useState<Alert[]>([]);
  const [dayLoading, setDayLoading] = useState(false);
  const [openAlertId, setOpenAlertId] = useState<number | null>(null);
  // 'all' or a sector name / company_id (as a string, to match <select>
  // values). Mutually exclusive -- picking one resets the other, since the
  // ask is "show just this sector" OR "show just this company", not both.
  const [sectorFilter, setSectorFilter] = useState('all');
  const [companyFilter, setCompanyFilter] = useState('all');

  // Reset to the current month and month view every time the modal is reopened.
  useEffect(() => {
    if (open) {
      const t = todayIst();
      setToday(t);
      setCursor({ year: t.year, month: t.month });
      setSelectedDate(null);
      setSectorFilter('all');
      setCompanyFilter('all');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setCountsLoading(true);
    getCalendarCounts(cursor.year, cursor.month)
      .then((data) => {
        if (active) setCounts(data);
      })
      .catch(() => {
        if (active) setCounts({});
      })
      .finally(() => {
        if (active) setCountsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [open, cursor]);

  useEffect(() => {
    if (selectedDate === null) return;
    let active = true;
    setDayLoading(true);
    getCalendarDay(selectedDate, language)
      .then((data) => {
        if (active) setDayAlerts(data);
      })
      .catch(() => {
        if (active) setDayAlerts([]);
      })
      .finally(() => {
        if (active) setDayLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedDate, language]);

  function changeMonth(delta: number) {
    setCursor((prev) => {
      const total = prev.year * 12 + (prev.month - 1) + delta;
      return { year: Math.floor(total / 12), month: (total % 12) + 1 };
    });
  }

  function openDay(key: string) {
    setSectorFilter('all');
    setCompanyFilter('all');
    setSelectedDate(key);
  }

  // AlertDetail's Escape handling is a plain `document` keydown listener with
  // no notion of other open modals -- with two AlertDetail instances open at
  // once (this one, and the nested one below for the alert popup), pressing
  // Escape fires BOTH listeners on the same keypress: the inner one closes
  // the alert, but the outer one (this handler) would also unconditionally
  // close the whole calendar. Guarding it to dismiss just the alert popup
  // when one is open keeps Escape (and the visible X, which shares this same
  // handler) scoped to the topmost layer instead of always exiting entirely.
  function closeOuter() {
    if (openAlertId !== null) {
      setOpenAlertId(null);
      return;
    }
    setSelectedDate(null);
    onClose();
  }

  const monthLabel = new Date(cursor.year, cursor.month - 1, 1).toLocaleDateString(undefined, {
    month: 'long',
    year: 'numeric',
  });

  const openAlert = dayAlerts.find((a) => a.id === openAlertId) ?? null;
  const cells: (number | null)[] = [];
  const total = daysInMonth(cursor.year, cursor.month);
  for (let i = 0; i < firstWeekday(cursor.year, cursor.month); i++) cells.push(null);
  for (let day = 1; day <= total; day++) cells.push(day);

  // Built from the day's already-fetched alerts -- no extra API call. Every
  // AlertCompany entry (direct_mention or sector_inference) counts as "this
  // company's news", so filtering by company_id membership already covers
  // both "the company's own story" and "news where it's shown as affected".
  const sectorOptions = useMemo(() => {
    const set = new Set<string>();
    dayAlerts.forEach((a) => a.companies.forEach((c) => {
      if (c.sector) set.add(c.sector);
    }));
    return Array.from(set).sort();
  }, [dayAlerts]);

  const companyOptions = useMemo(() => {
    const map = new Map<number, { id: number; name: string }>();
    dayAlerts.forEach((a) => a.companies.forEach((c) => {
      if (!map.has(c.company_id)) map.set(c.company_id, { id: c.company_id, name: c.name });
    }));
    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [dayAlerts]);

  const filteredDayAlerts = useMemo(() => {
    if (sectorFilter !== 'all') {
      return dayAlerts.filter((a) => a.companies.some((c) => c.sector === sectorFilter));
    }
    if (companyFilter !== 'all') {
      return dayAlerts.filter((a) => a.companies.some((c) => String(c.company_id) === companyFilter));
    }
    return dayAlerts;
  }, [dayAlerts, sectorFilter, companyFilter]);

  const dayHeader = selectedDate === null ? undefined : (
    <div className="flex flex-col gap-3 pr-8">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => setSelectedDate(null)}
          className="text-xs uppercase tracking-widest text-muted hover:text-ink"
        >
          ‹ {t('calendar.back')}
        </button>
        <h2 className="font-display text-lg font-bold text-ink">{selectedDate}</h2>
      </div>
      {dayAlerts.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs uppercase tracking-widest text-muted">
            {t('calendar.filterSector')}
            <select
              value={sectorFilter}
              onChange={(e) => {
                setSectorFilter(e.target.value);
                setCompanyFilter('all');
              }}
              className={SELECT_CLASS}
            >
              <option value="all">{t('calendar.filterAll')}</option>
              {sectorOptions.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-xs uppercase tracking-widest text-muted">
            {t('calendar.filterCompany')}
            <select
              value={companyFilter}
              onChange={(e) => {
                setCompanyFilter(e.target.value);
                setSectorFilter('all');
              }}
              className={SELECT_CLASS}
            >
              <option value="all">{t('calendar.filterAll')}</option>
              {companyOptions.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
    </div>
  );

  return (
    <AlertDetail open={open} onClose={closeOuter} fullScreenMobile header={dayHeader}>
      {selectedDate === null ? (
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between pr-8">
            <button
              type="button"
              onClick={() => changeMonth(-1)}
              aria-label={t('calendar.prevMonth')}
              className="flex h-8 w-8 items-center justify-center text-muted hover:text-ink"
            >
              ‹
            </button>
            <h2 className="font-display text-lg font-bold text-ink">{monthLabel}</h2>
            <button
              type="button"
              onClick={() => changeMonth(1)}
              aria-label={t('calendar.nextMonth')}
              className="flex h-8 w-8 items-center justify-center text-muted hover:text-ink"
            >
              ›
            </button>
          </div>
          <div className="grid grid-cols-7 gap-1 text-center">
            {WEEKDAY_LABELS.map((label, i) => (
              <div key={i} className="text-xs uppercase tracking-widest text-muted">
                {label}
              </div>
            ))}
            {cells.map((day, i) => {
              if (day === null) return <div key={`blank-${i}`} />;
              const key = dateKey(cursor.year, cursor.month, day);
              const count = counts[key] ?? 0;
              const isToday = key === dateKey(today.year, today.month, today.day);
              const clickable = count > 0;
              return (
                <button
                  key={key}
                  type="button"
                  disabled={!clickable}
                  onClick={() => openDay(key)}
                  className={`flex aspect-square flex-col items-center justify-center gap-0.5 rounded-lg text-sm ${
                    clickable
                      ? 'cursor-pointer text-ink hover:bg-surface theme-light:hover:shadow-neu-sm'
                      : 'cursor-default text-muted/50'
                  } ${isToday ? 'ring-1 ring-accent' : ''}`}
                >
                  <span>{day}</span>
                  {clickable && (
                    <span className="text-[10px] font-bold leading-none text-accent">{count}</span>
                  )}
                </button>
              );
            })}
          </div>
          {countsLoading && (
            <p className="text-center text-xs uppercase tracking-widest text-muted">{t('feed.loading')}</p>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {dayLoading ? (
            <p className="text-xs uppercase tracking-widest text-muted">{t('feed.loading')}</p>
          ) : dayAlerts.length === 0 ? (
            <p className="text-xs uppercase tracking-widest text-muted">{t('calendar.dayEmpty')}</p>
          ) : filteredDayAlerts.length === 0 ? (
            <p className="text-xs uppercase tracking-widest text-muted">{t('calendar.filterNoMatch')}</p>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {filteredDayAlerts.map((alert) => (
                <AlertCoverCard key={alert.id} alert={alert} variant="grid" onOpen={() => setOpenAlertId(alert.id)} />
              ))}
            </div>
          )}
        </div>
      )}
      <AlertDetail open={openAlertId !== null} onClose={() => setOpenAlertId(null)}>
        {openAlert && <AlertCompanies alert={openAlert} isAuthenticated={token !== null} />}
      </AlertDetail>
    </AlertDetail>
  );
}
