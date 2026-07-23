import type { Verdict } from './feedV2Api';

export function formatExcess(pct: number): { arrow: string; text: string } {
  const arrow = pct >= 0 ? '▲' : '▼';
  const text = `${arrow} ${Math.abs(pct).toFixed(1)}%`;
  return { arrow, text };
}

const VERDICT_LABELS: Record<Verdict, string> = {
  COMPANY_SPECIFIC: 'Company specific',
  SECTOR_WIDE: 'Sector wide',
  UNCONFIRMED: 'Unconfirmed',
};

export function verdictLabel(verdict: Verdict): string {
  return VERDICT_LABELS[verdict];
}

export function intensityBandColorClass(band: 'High' | 'Moderate' | 'Low'): string {
  if (band === 'High') return 'bg-intensityHigh';
  if (band === 'Moderate') return 'bg-intensityModerate';
  return 'bg-intensityLow';
}
