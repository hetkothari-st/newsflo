import type { AlertCompany } from '../../lib/api';
import { sectorColor } from './colors';

export interface CompanyGroup {
  key: string;
  label: string;
  color?: string;
  companies: AlertCompany[];
}

const TIER_ORDER = [
  'NIFTY50',
  'NIFTYNEXT50',
  'NIFTYMIDCAP150',
  'NIFTYSMALLCAP250',
  'GLOBAL_LARGE_CAP',
  'OTHER',
] as const;
const TIER_LABEL: Record<string, string> = {
  NIFTY50: 'Nifty 50',
  NIFTYNEXT50: 'Nifty Next 50',
  NIFTYMIDCAP150: 'Nifty Midcap 150',
  NIFTYSMALLCAP250: 'Nifty Smallcap 250',
  GLOBAL_LARGE_CAP: 'Global',
  OTHER: 'Other',
};

function tierKey(company: AlertCompany): string {
  return TIER_LABEL[company.index_tier] ? company.index_tier : 'OTHER';
}

export function groupByTier(companies: AlertCompany[]): CompanyGroup[] {
  return TIER_ORDER.map((tier) => ({
    key: tier,
    label: TIER_LABEL[tier],
    companies: companies.filter((c) => tierKey(c) === tier),
  })).filter((g) => g.companies.length > 0);
}

export function groupByImpact(companies: AlertCompany[]): CompanyGroup[] {
  const bullish = companies.filter((c) => c.direction === 'bullish');
  const bearish = companies.filter((c) => c.direction === 'bearish');

  const groups: CompanyGroup[] = [];
  if (bullish.length > 0) groups.push({ key: 'bullish', label: 'Bullish', companies: bullish });
  if (bearish.length > 0) groups.push({ key: 'bearish', label: 'Bearish', companies: bearish });
  return groups;
}

export function groupBySector(companies: AlertCompany[]): CompanyGroup[] {
  const bySector = new Map<string, AlertCompany[]>();
  for (const company of companies) {
    const sector = company.sector && company.sector.trim().length > 0 ? company.sector : 'Other';
    const group = bySector.get(sector) ?? [];
    group.push(company);
    bySector.set(sector, group);
  }

  return [...bySector.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([sector, group]) => ({ key: sector, label: sector, color: sectorColor(sector), companies: group }));
}
