// Pure, chart-agnostic data shaping for the deck charts. Everything here is
// a deterministic grouping/ordering of alert.companies -- reliable by
// construction (Doc-1's core premise). No fabrication: helpers only ever
// reorder or bucket real rows, never invent one.
import type { AlertCompany } from '../../../lib/api';
import { IMPACT_LEVEL_ORDER, impactLevelKey } from '../impactLevels';

export function groupByImpactLevel(companies: AlertCompany[]): Map<string, AlertCompany[]> {
  const groups = new Map<string, AlertCompany[]>(IMPACT_LEVEL_ORDER.map((level) => [level, []]));
  for (const company of companies) {
    groups.get(impactLevelKey(company))!.push(company);
  }
  return groups;
}

// "News · 22 Jul" -- the tree root's kicker line.
export function newsKickerLabel(alertCreatedAt: string): string {
  const date = new Date(alertCreatedAt);
  if (Number.isNaN(date.getTime())) return 'News';
  return `News · ${date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}`;
}

// Multi-Level Tree (#4): order a level's companies so children sit under
// their parent's x-position -- companies sharing a parent stay adjacent, and
// parent groups appear in the parent's own display order. Companies with no
// resolvable parent keep their relative order at the end.
export function orderByParent(companies: AlertCompany[], parentOrder: number[]): AlertCompany[] {
  const parentIndex = new Map(parentOrder.map((id, index) => [id, index]));
  return [...companies].sort((a, b) => {
    const ai = a.parent_company_id != null ? parentIndex.get(a.parent_company_id) ?? Number.MAX_SAFE_INTEGER : Number.MAX_SAFE_INTEGER;
    const bi = b.parent_company_id != null ? parentIndex.get(b.parent_company_id) ?? Number.MAX_SAFE_INTEGER : Number.MAX_SAFE_INTEGER;
    if (ai !== bi) return ai - bi;
    return companies.indexOf(a) - companies.indexOf(b);
  });
}

// Sort by measured-move magnitude, biggest first. Companies never measured
// (excess_move_pct null/absent) sort after every measured one -- they are
// not "0%", they are unknown.
export function sortByAbsMove(companies: AlertCompany[]): AlertCompany[] {
  return [...companies].sort((a, b) => {
    const am = a.excess_move_pct;
    const bm = b.excess_move_pct;
    if (am == null && bm == null) return 0;
    if (am == null) return 1;
    if (bm == null) return -1;
    return Math.abs(bm) - Math.abs(am);
  });
}

// Mean of the MEASURED moves only; null when nothing in the group has been
// measured (an honest "no reading yet", never a fabricated 0).
export function meanMove(companies: AlertCompany[]): number | null {
  const measured = companies.map((c) => c.excess_move_pct).filter((v): v is number => v != null);
  if (measured.length === 0) return null;
  return measured.reduce((sum, v) => sum + v, 0) / measured.length;
}

export function formatPct(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  return `${rounded > 0 ? '+' : ''}${text}%`;
}
