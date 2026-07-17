import type { Language } from './i18n';
import { translate } from './i18n';

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const WEEK_MS = 7 * DAY_MS;

// `now` is a required param (not `new Date()` internally) so this stays a
// pure, deterministically testable function -- callers pass the real
// current time in production and a fixed Date in tests.
export function formatRelativeTime(iso: string, now: Date, lang: Language): string {
  const then = new Date(iso);
  const diffMs = now.getTime() - then.getTime();

  if (diffMs < MINUTE_MS) return translate(lang, 'insights.justNow');
  if (diffMs < HOUR_MS) return translate(lang, 'insights.minutesAgo', { n: Math.floor(diffMs / MINUTE_MS) });
  if (diffMs < DAY_MS) return translate(lang, 'insights.hoursAgo', { n: Math.floor(diffMs / HOUR_MS) });
  if (diffMs < WEEK_MS) return translate(lang, 'insights.daysAgo', { n: Math.floor(diffMs / DAY_MS) });

  return then.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
