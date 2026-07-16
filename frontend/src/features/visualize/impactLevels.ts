import type { AlertCompany } from '../../lib/api';

export const IMPACT_LEVEL_ORDER = ['direct', 'indirect_l1', 'indirect_l2'] as const;

export const IMPACT_LEVEL_LABEL: Record<string, string> = {
  direct: 'Direct Impact',
  indirect_l1: 'Indirect Impact — Level 1',
  indirect_l2: 'Indirect Impact — Level 2',
};

// Reuses three already-validated hexes from colors.ts's SECTOR_COLOR (see
// that file's palette-validation comment) rather than introducing a new
// palette for a 3-value badge -- banking-blue/fmcg-green/auto-orange happen
// to match the mockup's direct=blue / L1=green / L2=orange convention.
export const IMPACT_LEVEL_COLOR: Record<string, string> = {
  direct: '#4A90D9',
  indirect_l1: '#3E9B5C',
  indirect_l2: '#C97F0E',
};

export function impactLevelKey(company: Pick<AlertCompany, 'impact_level'>): string {
  const level = company.impact_level;
  return level && IMPACT_LEVEL_LABEL[level] ? level : 'direct';
}

export function impactLevelLabel(level: string): string {
  return IMPACT_LEVEL_LABEL[level] ?? level;
}

export function impactLevelColor(level: string): string {
  return IMPACT_LEVEL_COLOR[level] ?? IMPACT_LEVEL_COLOR.direct;
}
