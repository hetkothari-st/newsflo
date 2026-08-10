import { describe, expect, it } from 'vitest';
import type { DirectoryCompany } from './api';
import {
  DEFAULT_DIRECTORY_FILTERS,
  applyDirectoryView,
  companyMatchesFilters,
  displaySector,
  indexTierOptions,
  parseFilterBound,
  sectorOptions,
  sortCompanies,
  subSectorOptions,
  type DirectoryFilterState,
} from './directoryFilters';

function company(overrides: Partial<DirectoryCompany>): DirectoryCompany {
  return {
    ticker: 'RELIANCE.NS',
    name: 'Reliance Industries',
    sector: 'oil_gas',
    cap_tier: 'LARGE',
    logo_url: null,
    market_cap: 17_000_000_000_000,
    index_tier: 'NIFTY50',
    sub_sector: 'refining_marketing',
    pe: 25.0,
    pb: 2.5,
    roe: 12.0,
    ...overrides,
  };
}

function filters(overrides: Partial<DirectoryFilterState>): DirectoryFilterState {
  return { ...DEFAULT_DIRECTORY_FILTERS, ...overrides };
}

describe('parseFilterBound', () => {
  it('treats empty and whitespace as no bound', () => {
    expect(parseFilterBound('')).toBeNull();
    expect(parseFilterBound('   ')).toBeNull();
  });

  it('parses numbers and rejects garbage', () => {
    expect(parseFilterBound('12.5')).toBe(12.5);
    expect(parseFilterBound('-8')).toBe(-8);
    expect(parseFilterBound('abc')).toBeNull();
  });
});

describe('companyMatchesFilters search', () => {
  it('matches name and ticker case-insensitively', () => {
    expect(companyMatchesFilters(company({}), filters({ search: 'reliance' }))).toBe(true);
    expect(companyMatchesFilters(company({}), filters({ search: 'RELI' }))).toBe(true);
    expect(companyMatchesFilters(company({}), filters({ search: 'tcs' }))).toBe(false);
  });

  it('empty search matches everything', () => {
    expect(companyMatchesFilters(company({}), filters({ search: '  ' }))).toBe(true);
  });
});

describe('companyMatchesFilters categorical', () => {
  it('cap tier exact match with ALL bypass', () => {
    expect(companyMatchesFilters(company({}), filters({ capTier: 'LARGE' }))).toBe(true);
    expect(companyMatchesFilters(company({}), filters({ capTier: 'MID' }))).toBe(false);
    expect(companyMatchesFilters(company({ cap_tier: null }), filters({ capTier: 'ALL' }))).toBe(true);
  });

  it('index tier exact match', () => {
    expect(companyMatchesFilters(company({}), filters({ indexTier: 'NIFTY50' }))).toBe(true);
    expect(companyMatchesFilters(company({}), filters({ indexTier: 'OTHER' }))).toBe(false);
  });

  it('sub-sector is ignored when sector is ALL', () => {
    expect(
      companyMatchesFilters(company({}), filters({ sector: 'ALL', subSector: 'banks_private' })),
    ).toBe(true);
  });

  it('sub-sector applies within a chosen sector and excludes null sub_sector', () => {
    const f = filters({ sector: 'oil_gas', subSector: 'refining_marketing' });
    expect(companyMatchesFilters(company({}), f)).toBe(true);
    expect(companyMatchesFilters(company({ sub_sector: null }), f)).toBe(false);
    expect(companyMatchesFilters(company({ sub_sector: 'upstream' }), f)).toBe(false);
  });
});

describe('companyMatchesFilters fundamentals ranges', () => {
  it('null metric passes when that range is inactive', () => {
    expect(companyMatchesFilters(company({ pe: null }), filters({}))).toBe(true);
  });

  it('null metric drops out only when its own range is active', () => {
    // peMin active: pe=null fails even though pb is fine.
    expect(
      companyMatchesFilters(company({ pe: null, pb: 5 }), filters({ peMin: '10' })),
    ).toBe(false);
    // pb untouched: pb=null passes while pe filter is active and satisfied.
    expect(
      companyMatchesFilters(company({ pe: 12, pb: null }), filters({ peMin: '10' })),
    ).toBe(true);
  });

  it('min and max bounds are inclusive-range checks', () => {
    expect(companyMatchesFilters(company({ pe: 25 }), filters({ peMin: '20', peMax: '30' }))).toBe(true);
    expect(companyMatchesFilters(company({ pe: 19.9 }), filters({ peMin: '20' }))).toBe(false);
    expect(companyMatchesFilters(company({ pe: 30.1 }), filters({ peMax: '30' }))).toBe(false);
  });

  it('negative ROE is a real value, filterable', () => {
    expect(companyMatchesFilters(company({ roe: -8.4 }), filters({ roeMax: '0' }))).toBe(true);
    expect(companyMatchesFilters(company({ roe: -8.4 }), filters({ roeMin: '0' }))).toBe(false);
  });

  it('garbage input is treated as no bound, not zero', () => {
    expect(companyMatchesFilters(company({ pe: null }), filters({ peMin: 'abc' }))).toBe(true);
  });
});

describe('sortCompanies', () => {
  const a = company({ ticker: 'A.NS', name: 'Zeta', market_cap: 100 });
  const b = company({ ticker: 'B.NS', name: 'Alpha', market_cap: null });
  const c = company({ ticker: 'C.NS', name: 'Midway', market_cap: 300 });

  it('sorts by ticker by default', () => {
    expect(sortCompanies([c, a, b], 'ticker').map((x) => x.ticker)).toEqual(['A.NS', 'B.NS', 'C.NS']);
  });

  it('sorts by name', () => {
    expect(sortCompanies([a, b, c], 'name').map((x) => x.name)).toEqual(['Alpha', 'Midway', 'Zeta']);
  });

  it('sorts by market cap desc with nulls last', () => {
    expect(sortCompanies([a, b, c], 'market_cap_desc').map((x) => x.ticker)).toEqual([
      'C.NS', 'A.NS', 'B.NS',
    ]);
  });

  it('does not mutate the input array', () => {
    const input = [c, a];
    sortCompanies(input, 'ticker');
    expect(input.map((x) => x.ticker)).toEqual(['C.NS', 'A.NS']);
  });
});

describe('option derivation', () => {
  const list = [
    company({ ticker: 'A.NS', sector: 'it', sub_sector: 'services', index_tier: 'NIFTY50' }),
    company({ ticker: 'B.NS', sector: 'it', sub_sector: null, index_tier: 'OTHER' }),
    company({ ticker: 'C.NS', sector: 'other', sub_sector: null, index_tier: 'OTHER' }),
  ];

  it('sectorOptions dedupes and sorts', () => {
    expect(sectorOptions(list)).toEqual(['ALL', 'it', 'other']);
  });

  it('subSectorOptions is empty when no sector chosen', () => {
    expect(subSectorOptions(list, 'ALL')).toEqual([]);
  });

  it('subSectorOptions excludes nulls, empty when the sector has none', () => {
    expect(subSectorOptions(list, 'it')).toEqual(['ALL', 'services']);
    // "other" sector has no sub-sector taxonomy -- drilldown must hide.
    expect(subSectorOptions(list, 'other')).toEqual([]);
  });

  it('indexTierOptions derives from data, not a hardcoded list', () => {
    expect(indexTierOptions(list)).toEqual(['ALL', 'NIFTY50', 'OTHER']);
  });
});

describe('displaySector banking/finance bifurcation', () => {
  it('non-banking sectors pass through unchanged', () => {
    expect(displaySector(company({ sector: 'it', sub_sector: 'services' }))).toBe('it');
    expect(displaySector(company({ sector: 'other', sub_sector: null }))).toBe('other');
  });

  it('non-bank financials become the derived finance sector', () => {
    for (const sub of ['nbfc', 'housing_finance', 'insurance', 'asset_management']) {
      expect(displaySector(company({ sector: 'banking', sub_sector: sub }))).toBe('finance');
    }
  });

  it('banks and unclassified banking rows stay banking', () => {
    expect(displaySector(company({ sector: 'banking', sub_sector: 'private_bank' }))).toBe('banking');
    expect(displaySector(company({ sector: 'banking', sub_sector: 'psu_bank' }))).toBe('banking');
    expect(displaySector(company({ sector: 'banking', sub_sector: 'banking_other' }))).toBe('banking');
    expect(displaySector(company({ sector: 'banking', sub_sector: null }))).toBe('banking');
  });

  it('sector filter matches the derived sector, not the stored one', () => {
    const nbfc = company({ sector: 'banking', sub_sector: 'nbfc' });
    const bank = company({ sector: 'banking', sub_sector: 'psu_bank' });
    expect(companyMatchesFilters(nbfc, filters({ sector: 'finance' }))).toBe(true);
    expect(companyMatchesFilters(bank, filters({ sector: 'finance' }))).toBe(false);
    expect(companyMatchesFilters(nbfc, filters({ sector: 'banking' }))).toBe(false);
    expect(companyMatchesFilters(bank, filters({ sector: 'banking' }))).toBe(true);
  });

  it('sectorOptions lists banking and finance when both are present', () => {
    const list = [
      company({ ticker: 'HDFC.NS', sector: 'banking', sub_sector: 'private_bank' }),
      company({ ticker: 'LIC.NS', sector: 'banking', sub_sector: 'insurance' }),
    ];
    expect(sectorOptions(list)).toEqual(['ALL', 'banking', 'finance']);
  });

  it('sub-sector drilldown splits along the bifurcation', () => {
    const list = [
      company({ ticker: 'HDFC.NS', sector: 'banking', sub_sector: 'private_bank' }),
      company({ ticker: 'SBI.NS', sector: 'banking', sub_sector: 'psu_bank' }),
      company({ ticker: 'LIC.NS', sector: 'banking', sub_sector: 'insurance' }),
      company({ ticker: 'BAJFIN.NS', sector: 'banking', sub_sector: 'nbfc' }),
    ];
    expect(subSectorOptions(list, 'banking')).toEqual(['ALL', 'private_bank', 'psu_bank']);
    expect(subSectorOptions(list, 'finance')).toEqual(['ALL', 'insurance', 'nbfc']);
  });
});

describe('applyDirectoryView', () => {
  it('filters then sorts', () => {
    const list = [
      company({ ticker: 'B.NS', name: 'Beta', sector: 'it', market_cap: 100 }),
      company({ ticker: 'A.NS', name: 'Alpha', sector: 'it', market_cap: 200 }),
      company({ ticker: 'X.NS', name: 'Xi', sector: 'pharma', market_cap: 900 }),
    ];
    const result = applyDirectoryView(list, filters({ sector: 'it', sort: 'market_cap_desc' }));
    expect(result.map((x) => x.ticker)).toEqual(['A.NS', 'B.NS']);
  });
});
