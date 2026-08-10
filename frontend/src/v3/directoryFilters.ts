/* Pure filter/sort logic for the Directory view -- no React, unit-tested
   directly (same split as lib/feedFilters.ts). */
import type { CapTier, DirectoryCompany } from './api';

export type DirectorySort = 'ticker' | 'name' | 'market_cap_desc';

export interface DirectoryFilterState {
  search: string;
  capTier: CapTier | 'ALL';
  sector: string;
  subSector: string; // ignored unless sector !== 'ALL'
  indexTier: string; // 'ALL' or a value present in the fetched data
  peMin: string;
  peMax: string;
  pbMin: string;
  pbMax: string;
  roeMin: string;
  roeMax: string;
  sort: DirectorySort;
}

export const DEFAULT_DIRECTORY_FILTERS: DirectoryFilterState = {
  search: '',
  capTier: 'ALL',
  sector: 'ALL',
  subSector: 'ALL',
  indexTier: 'ALL',
  peMin: '',
  peMax: '',
  pbMin: '',
  pbMax: '',
  roeMin: '',
  roeMax: '',
  sort: 'ticker',
};

// '' or non-numeric text is "no bound", never zero.
export function parseFilterBound(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === '') return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

// A company with a null metric drops out ONLY when this metric's range is
// active -- an untouched filter must not hide the ~50% of companies without
// BSE ratios.
function passesRange(value: number | null, minRaw: string, maxRaw: string): boolean {
  const min = parseFilterBound(minRaw);
  const max = parseFilterBound(maxRaw);
  if (min === null && max === null) return true;
  if (value === null) return false;
  if (min !== null && value < min) return false;
  if (max !== null && value > max) return false;
  return true;
}

function matchesSearch(company: DirectoryCompany, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === '') return true;
  return company.name.toLowerCase().includes(q) || company.ticker.toLowerCase().includes(q);
}

// The backend's closed sector taxonomy keeps all financials under "banking"
// (BSE "financial services" maps there). The directory bifurcates that bucket
// for display: non-bank financials become a derived "finance" sector. Display
// only -- Company.sector is untouched (it is rewritten by the monthly universe
// refresh, so a stored split would revert).
const FINANCE_SUB_SECTORS = new Set(['nbfc', 'housing_finance', 'insurance', 'asset_management']);

export function displaySector(company: DirectoryCompany): string {
  if (company.sector !== 'banking') return company.sector;
  // Unclassified (null sub_sector) banking rows stay under Banking.
  return company.sub_sector !== null && FINANCE_SUB_SECTORS.has(company.sub_sector)
    ? 'finance'
    : 'banking';
}

export function companyMatchesFilters(company: DirectoryCompany, f: DirectoryFilterState): boolean {
  if (!matchesSearch(company, f.search)) return false;
  if (f.capTier !== 'ALL' && company.cap_tier !== f.capTier) return false;
  if (f.sector !== 'ALL' && displaySector(company) !== f.sector) return false;
  if (f.sector !== 'ALL' && f.subSector !== 'ALL' && company.sub_sector !== f.subSector) return false;
  if (f.indexTier !== 'ALL' && company.index_tier !== f.indexTier) return false;
  if (!passesRange(company.pe, f.peMin, f.peMax)) return false;
  if (!passesRange(company.pb, f.pbMin, f.pbMax)) return false;
  if (!passesRange(company.roe, f.roeMin, f.roeMax)) return false;
  return true;
}

export function sortCompanies(companies: DirectoryCompany[], sort: DirectorySort): DirectoryCompany[] {
  const sorted = [...companies];
  if (sort === 'name') sorted.sort((a, b) => a.name.localeCompare(b.name));
  else if (sort === 'market_cap_desc') {
    sorted.sort((a, b) => (b.market_cap ?? -Infinity) - (a.market_cap ?? -Infinity));
  } else sorted.sort((a, b) => a.ticker.localeCompare(b.ticker));
  return sorted;
}

export function applyDirectoryView(
  companies: DirectoryCompany[],
  f: DirectoryFilterState,
): DirectoryCompany[] {
  return sortCompanies(companies.filter((c) => companyMatchesFilters(c, f)), f.sort);
}

function uniqueSorted(values: (string | null)[]): string[] {
  return Array.from(new Set(values.filter((v): v is string => v !== null))).sort();
}

export function sectorOptions(companies: DirectoryCompany[]): string[] {
  return ['ALL', ...uniqueSorted(companies.map(displaySector))];
}

// Empty (not ['ALL']) when no sector chosen or the sector has no classified
// sub-sectors ("other" never does) -- the caller hides the drilldown then.
// Keyed on displaySector, so Banking offers bank sub-sectors and Finance
// offers only the non-bank financial ones.
export function subSectorOptions(companies: DirectoryCompany[], sector: string): string[] {
  if (sector === 'ALL') return [];
  const subs = uniqueSorted(
    companies.filter((c) => displaySector(c) === sector).map((c) => c.sub_sector),
  );
  return subs.length === 0 ? [] : ['ALL', ...subs];
}

// Derived from the data, not hardcoded, so an unexpected tier value (e.g. a
// GLOBAL row ever gaining a market_cap) stays selectable instead of invisible.
export function indexTierOptions(companies: DirectoryCompany[]): string[] {
  return ['ALL', ...uniqueSorted(companies.map((c) => c.index_tier))];
}
