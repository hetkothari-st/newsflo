import type { AlertCompany } from '../../lib/api';
import { sectorColor } from './colors';
import { subSectorKey, subSectorLabel, UNCLASSIFIED_KEY } from './subSectorLabels';

export type GroupMode = 'tier' | 'impact' | 'sector';

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

const SECTOR_LABEL: Record<string, string> = {
  oil_gas: 'Oil & Gas',
  banking: 'Banking',
  auto: 'Auto',
  it: 'IT',
  pharma: 'Pharma',
  fmcg: 'FMCG',
  metals: 'Metals',
  telecom: 'Telecom',
  infra: 'Infrastructure',
  other: 'Other',
};

export function sectorLabel(sector: string): string {
  return SECTOR_LABEL[sector] ?? sector;
}

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
    .map(([sector, group]) => ({
      key: sector,
      label: sectorLabel(sector),
      color: sectorColor(sector),
      companies: group,
    }));
}

function magnitudeMidpoint(company: AlertCompany): number {
  return (company.magnitude_low + company.magnitude_high) / 2;
}

// Ordinal ranking, not a claim about absolute scale -- magnitude_low/high
// values span roughly 0-100 with no fixed calibration, so this only ever
// answers "stronger than the others in THIS alert's company list," never
// "this company moved N%." See docs/superpowers/specs/2026-07-14-charts-page-v3-design.md.
export function rankByMagnitude(companies: AlertCompany[]): AlertCompany[] {
  return [...companies].sort((a, b) => magnitudeMidpoint(b) - magnitudeMidpoint(a));
}

export function rankByConfidence(companies: AlertCompany[]): AlertCompany[] {
  return [...companies].sort((a, b) => b.confidence_score - a.confidence_score);
}

export const TIME_HORIZON_ORDER = ['Immediate', 'Short-Term', 'Medium-Term', 'Long-Term'] as const;

export function groupByTimeHorizon(companies: AlertCompany[]): CompanyGroup[] {
  return TIME_HORIZON_ORDER.map((horizon) => ({
    key: horizon,
    label: horizon,
    companies: companies.filter((c) => c.time_horizon === horizon),
  })).filter((g) => g.companies.length > 0);
}

export interface NetSignal {
  direction: 'bullish' | 'bearish' | 'even';
  bullishCount: number;
  bearishCount: number;
  avgConfidence: number; // mean confidence_score across the group, rounded, 0 for an empty group
}

// Deterministic, DB-free aggregation over data already present on each
// AlertCompany (direction, confidence_score) -- no new LLM calls, no network
// round-trip. Shared by TierRows' inline net-sentiment glyph and the
// sector/sub-sector drilldown branches.
export function computeNetSignal(companies: AlertCompany[]): NetSignal {
  const bullishCount = companies.filter((c) => c.direction === 'bullish').length;
  const bearishCount = companies.length - bullishCount;
  const direction: NetSignal['direction'] =
    bullishCount === bearishCount ? 'even' : bullishCount > bearishCount ? 'bullish' : 'bearish';
  const avgConfidence =
    companies.length === 0
      ? 0
      : Math.round(companies.reduce((sum, c) => sum + c.confidence_score, 0) / companies.length);
  return { direction, bullishCount, bearishCount, avgConfidence };
}

// "High/Medium/Low Positive/Negative" -- matches the reference mockup's
// severity-badge convention exactly, derived from data already computed by
// computeNetSignal rather than a separate LLM-provided severity field (which
// doesn't exist). "Mixed" for an even split, since there's no single
// direction to grade the intensity of.
export function severityLabel(signal: NetSignal): string {
  if (signal.direction === 'even') return 'Mixed';
  const intensity = signal.avgConfidence >= 70 ? 'High' : signal.avgConfidence >= 40 ? 'Medium' : 'Low';
  const polarity = signal.direction === 'bullish' ? 'Positive' : 'Negative';
  return `${intensity} ${polarity}`;
}

export interface SubSectorGroup extends CompanyGroup {
  netSignal: NetSignal;
}

export interface SectorDrilldownGroup extends CompanyGroup {
  netSignal: NetSignal;
  subSectorGroups: SubSectorGroup[];
}

// Two-level grouping for the Sector chart's real drilldown: sector (reuses
// groupBySector) -> sub_sector (new). A sector with only one distinct
// sub_sector bucket present (including the all-null/all-unclassified case)
// collapses to a flat sector -> company view at render time -- see
// SectorTree.tsx -- so the extra tree depth only appears when it's actually
// informative.
export function groupBySectorAndSubSector(companies: AlertCompany[]): SectorDrilldownGroup[] {
  return groupBySector(companies).map((sectorGroup) => {
    const bySub = new Map<string, AlertCompany[]>();
    for (const c of sectorGroup.companies) {
      const key = subSectorKey(c.sub_sector);
      const group = bySub.get(key) ?? [];
      group.push(c);
      bySub.set(key, group);
    }
    const subSectorGroups: SubSectorGroup[] = [...bySub.entries()]
      .sort(([a], [b]) => subSectorLabel(a === UNCLASSIFIED_KEY ? null : a).localeCompare(
        subSectorLabel(b === UNCLASSIFIED_KEY ? null : b),
      ))
      .map(([key, group]) => ({
        key,
        label: subSectorLabel(key === UNCLASSIFIED_KEY ? null : key),
        companies: group,
        netSignal: computeNetSignal(group),
      }));
    return { ...sectorGroup, netSignal: computeNetSignal(sectorGroup.companies), subSectorGroups };
  });
}
