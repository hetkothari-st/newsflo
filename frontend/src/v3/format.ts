/* Display helpers for the card-feed UI -- direct ports of the prototype's
   fmt/capC/liqS/arr/col helpers plus label maps (spec v2 §7). */
import type { CapTier, IntensityComponent, LiquidityTier, Verdict } from './api';

export function fmtPct(n: number): string {
  return (n > 0 ? '+' : '') + n.toFixed(1) + '%';
}

export function capClass(cap: CapTier | null): string {
  if (cap === 'LARGE') return 'cap-L';
  if (cap === 'MID') return 'cap-M';
  if (cap === 'SMALL') return 'cap-S';
  return 'cap-U';
}

export function liqShort(liq: LiquidityTier): string {
  return { LOW: 'LOW', MODERATE: 'MOD', HIGH: 'HIGH' }[liq];
}

export type MoveDir = 'up' | 'down' | 'flat';

export function moveDir(excess: number, verdict: Verdict): MoveDir {
  // The prototype renders an UNCONFIRMED move in the muted "flat" style --
  // an unverified report's number should not shout a direction.
  if (verdict === 'UNCONFIRMED') return 'flat';
  return excess >= 0 ? 'up' : 'down';
}

export function arrow(dir: MoveDir): string {
  return dir === 'up' ? '▲' : dir === 'down' ? '▼' : '▬';
}

export function moveColor(value: number | null): string {
  if (value == null || value === 0) return 'var(--ink3)';
  return value > 0 ? 'var(--up)' : 'var(--down)';
}

export function bandClass(score: number): 'hi' | 'mid' | 'lo' {
  return score >= 75 ? 'hi' : score >= 50 ? 'mid' : 'lo';
}

export const VERDICT_LABELS: Record<Verdict, string> = {
  COMPANY_SPECIFIC: 'Company-specific',
  SECTOR_WIDE: 'Sector-wide',
  UNCONFIRMED: 'Unconfirmed',
};

export function verdictClass(verdict: Verdict): string {
  if (verdict === 'COMPANY_SPECIFIC') return 'v-company';
  if (verdict === 'UNCONFIRMED') return 'v-unconf';
  return 'v-sector';
}

export const COMPONENT_LABELS: Record<string, string> = {
  excess: 'Excess',
  volume: 'Volume',
  delivery: 'Delivery',
  materiality: 'Materiality',
  vol_norm: 'Vol-norm',
  fundamental: 'Fundamental',
};

export function componentLabel(component: IntensityComponent): string {
  return COMPONENT_LABELS[component.label] ?? component.label;
}

export function fmtVolume(multiple: number | null): string {
  return multiple == null ? '—' : `${multiple.toFixed(1)}×`;
}

export function fmtTime(iso: string): string {
  // IST clock time, matching the prototype's "11:02" meta style.
  return new Date(iso).toLocaleTimeString('en-IN', {
    hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata',
  });
}

export const TIMELINE_COLORS: Record<string, string> = {
  TODAY: 'var(--down)',
  DAYS: 'var(--amber)',
  WEEKS: 'var(--accent)',
  MONTHS: 'var(--accent)',
  QUARTERS: 'var(--accent)',
};

export function horizonLabel(horizon: string): string {
  return horizon.charAt(0) + horizon.slice(1).toLowerCase();
}

export const LOW_DELIVERY_THRESHOLD_PCT = 50;

export function isLowDelivery(deliveryPct: number | null): boolean {
  return deliveryPct != null && deliveryPct < LOW_DELIVERY_THRESHOLD_PCT;
}

export function isThinTrading(liq: LiquidityTier | null, cap: CapTier | null): boolean {
  return liq === 'LOW' && (cap === 'SMALL' || cap === 'MICRO');
}
