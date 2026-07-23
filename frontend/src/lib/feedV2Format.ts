import type { CapTier, RippleRelationship, Verdict } from './feedV2Api';

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

const RELATIONSHIP_LABELS: Record<RippleRelationship, string> = {
  BENEFICIARY: 'Beneficiary',
  CUSTOMER_INPUT_COST: 'Customer / input cost',
  SUPPLIER: 'Supplier',
  SUBSTITUTE: 'Substitute',
  COMPETITOR: 'Competitor',
  SECTOR_WIDE: 'Sector wide',
};

export function relationshipLabel(relationship: RippleRelationship): string {
  return RELATIONSHIP_LABELS[relationship];
}

export function intensityBandColorClass(band: 'High' | 'Moderate' | 'Low'): string {
  if (band === 'High') return 'bg-intensityHigh';
  if (band === 'Moderate') return 'bg-intensityModerate';
  return 'bg-intensityLow';
}

export function capTierColorClass(tier: CapTier): string {
  if (tier === 'LARGE') return 'bg-capLarge/15 text-capLarge';
  if (tier === 'MID') return 'bg-capMid/15 text-capMid';
  return 'bg-capSmall/15 text-capSmall';
}
