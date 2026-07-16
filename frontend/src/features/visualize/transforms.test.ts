import { describe, expect, it } from 'vitest';
import {
  groupByTier, groupByImpact, groupBySector, sectorLabel, rankByMagnitude, rankByConfidence,
  groupByTimeHorizon, computeNetSignal, groupBySectorAndSubSector,
} from './transforms';
import type { AlertCompany } from '../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('groupByTier', () => {
  it('orders groups Nifty 50 -> Next 50 -> Midcap 150 -> Smallcap 250 -> Global -> Other', () => {
    const groups = groupByTier([
      company({ company_id: 1, index_tier: 'OTHER' }),
      company({ company_id: 2, index_tier: 'GLOBAL_LARGE_CAP' }),
      company({ company_id: 3, index_tier: 'NIFTY50' }),
      company({ company_id: 4, index_tier: 'NIFTYNEXT50' }),
      company({ company_id: 5, index_tier: 'NIFTYMIDCAP150' }),
      company({ company_id: 6, index_tier: 'NIFTYSMALLCAP250' }),
    ]);
    expect(groups.map((g) => g.label)).toEqual([
      'Nifty 50', 'Nifty Next 50', 'Nifty Midcap 150', 'Nifty Smallcap 250', 'Global', 'Other',
    ]);
  });

  it('falls back unrecognized tiers to Other', () => {
    const groups = groupByTier([company({ index_tier: 'SMALLCAP' })]);
    expect(groups.map((g) => g.label)).toEqual(['Other']);
  });

  it('omits a tier group with zero companies', () => {
    const groups = groupByTier([company({ index_tier: 'NIFTY50' })]);
    expect(groups.map((g) => g.label)).toEqual(['Nifty 50']);
  });
});

describe('groupByImpact', () => {
  it('splits companies into Bullish and Bearish groups', () => {
    const groups = groupByImpact([
      company({ company_id: 1, direction: 'bullish' }),
      company({ company_id: 2, direction: 'bearish' }),
    ]);
    expect(groups.map((g) => g.label)).toEqual(['Bullish', 'Bearish']);
    expect(groups[0].companies).toHaveLength(1);
    expect(groups[1].companies).toHaveLength(1);
  });

  it('omits a group with zero companies rather than rendering it empty', () => {
    const groups = groupByImpact([company({ direction: 'bullish' })]);
    expect(groups.map((g) => g.label)).toEqual(['Bullish']);
  });

  it('excludes companies whose direction is neither bullish nor bearish', () => {
    const groups = groupByImpact([company({ direction: 'unknown' })]);
    expect(groups).toHaveLength(0);
  });

  it('excludes an unrecognized-direction company while still bucketing its bullish/bearish siblings', () => {
    const groups = groupByImpact([
      company({ company_id: 1, direction: 'bullish' }),
      company({ company_id: 2, direction: 'bearish' }),
      company({ company_id: 3, direction: 'unknown' }),
    ]);
    const bullish = groups.find((g) => g.label === 'Bullish');
    const bearish = groups.find((g) => g.label === 'Bearish');
    expect(bullish?.companies).toHaveLength(1);
    expect(bearish?.companies).toHaveLength(1);
    expect(groups).toHaveLength(2);
  });
});

describe('groupBySector', () => {
  it('groups companies by sector, alphabetically', () => {
    const groups = groupBySector([
      company({ company_id: 1, sector: 'Financials' }),
      company({ company_id: 2, sector: 'Energy' }),
      company({ company_id: 3, sector: 'Energy' }),
    ]);
    expect(groups.map((g) => g.label)).toEqual(['Energy', 'Financials']);
    expect(groups[0].companies).toHaveLength(2);
  });

  it('groups companies with no sector under "Other"', () => {
    const groups = groupBySector([company({ sector: undefined })]);
    expect(groups.map((g) => g.label)).toEqual(['Other']);
  });

  it('groups companies with an empty or whitespace-only sector under "Other"', () => {
    const groups = groupBySector([
      company({ company_id: 1, sector: '' }),
      company({ company_id: 2, sector: '   ' }),
    ]);
    expect(groups.map((g) => g.label)).toEqual(['Other']);
    expect(groups[0].companies).toHaveLength(2);
  });

  it('assigns each sector group a deterministic color', () => {
    const groups = groupBySector([company({ sector: 'Energy' })]);
    expect(groups[0].color).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });
});

describe('sectorLabel', () => {
  it('maps known sector slugs to a human-readable label', () => {
    expect(sectorLabel('oil_gas')).toBe('Oil & Gas');
    expect(sectorLabel('it')).toBe('IT');
  });

  it('falls back to the raw string for an unrecognized sector', () => {
    expect(sectorLabel('some_future_sector')).toBe('some_future_sector');
  });
});

describe('rankByMagnitude', () => {
  it('sorts descending by the midpoint of magnitude_low and magnitude_high', () => {
    const weak = company({ company_id: 1, magnitude_low: 0, magnitude_high: 1 });
    const strong = company({ company_id: 2, magnitude_low: 8, magnitude_high: 12 });
    const mid = company({ company_id: 3, magnitude_low: 2, magnitude_high: 4 });

    expect(rankByMagnitude([weak, strong, mid]).map((c) => c.company_id)).toEqual([2, 3, 1]);
  });

  it('keeps input order for equal midpoints (stable sort)', () => {
    const a = company({ company_id: 1, magnitude_low: 1, magnitude_high: 3 });
    const b = company({ company_id: 2, magnitude_low: 0, magnitude_high: 4 });

    expect(rankByMagnitude([a, b]).map((c) => c.company_id)).toEqual([1, 2]);
  });

  it('returns an empty array for an empty input', () => {
    expect(rankByMagnitude([])).toEqual([]);
  });

  it('returns a single-element array unchanged', () => {
    const only = company({ company_id: 1 });
    expect(rankByMagnitude([only])).toEqual([only]);
  });
});

describe('rankByConfidence', () => {
  it('sorts descending by confidence_score', () => {
    const weak = company({ company_id: 1, confidence_score: 40 });
    const strong = company({ company_id: 2, confidence_score: 95 });
    const mid = company({ company_id: 3, confidence_score: 70 });

    expect(rankByConfidence([weak, strong, mid]).map((c) => c.company_id)).toEqual([2, 3, 1]);
  });

  it('keeps input order for equal scores (stable sort)', () => {
    const a = company({ company_id: 1, confidence_score: 80 });
    const b = company({ company_id: 2, confidence_score: 80 });

    expect(rankByConfidence([a, b]).map((c) => c.company_id)).toEqual([1, 2]);
  });

  it('returns an empty array for an empty input', () => {
    expect(rankByConfidence([])).toEqual([]);
  });
});

describe('groupByTimeHorizon', () => {
  it('groups companies into fixed-order horizon buckets, dropping empty ones', () => {
    const groups = groupByTimeHorizon([
      company({ company_id: 1, time_horizon: 'Long-Term' }),
      company({ company_id: 2, time_horizon: 'Immediate' }),
      company({ company_id: 3, time_horizon: 'Immediate' }),
    ]);
    expect(groups.map((g) => g.key)).toEqual(['Immediate', 'Long-Term']);
    expect(groups[0].companies).toHaveLength(2);
    expect(groups[1].companies).toHaveLength(1);
  });

  it('returns an empty array for an empty input', () => {
    expect(groupByTimeHorizon([])).toEqual([]);
  });
});

describe('computeNetSignal', () => {
  it('returns even with zero avgConfidence for an empty list', () => {
    expect(computeNetSignal([])).toEqual({ direction: 'even', bullishCount: 0, bearishCount: 0, avgConfidence: 0 });
  });

  it('reports net bullish and the mean confidence when bullish outnumbers bearish', () => {
    const signal = computeNetSignal([
      company({ direction: 'bullish', confidence_score: 80 }),
      company({ direction: 'bullish', confidence_score: 60 }),
      company({ direction: 'bearish', confidence_score: 40 }),
    ]);
    expect(signal.direction).toBe('bullish');
    expect(signal.bullishCount).toBe(2);
    expect(signal.bearishCount).toBe(1);
    expect(signal.avgConfidence).toBe(60);
  });

  it('reports even on an exact tie', () => {
    const signal = computeNetSignal([
      company({ direction: 'bullish' }),
      company({ direction: 'bearish' }),
    ]);
    expect(signal.direction).toBe('even');
  });
});

describe('groupBySectorAndSubSector', () => {
  it('buckets companies with no sub_sector into a single Unclassified group', () => {
    const [sector] = groupBySectorAndSubSector([
      company({ company_id: 1, sector: 'banking', sub_sector: null }),
      company({ company_id: 2, sector: 'banking', sub_sector: null }),
    ]);
    expect(sector.subSectorGroups).toHaveLength(1);
    expect(sector.subSectorGroups[0].label).toBe('Unclassified');
    expect(sector.subSectorGroups[0].companies).toHaveLength(2);
  });

  it('splits into separate branches when distinct sub_sectors are present', () => {
    const [sector] = groupBySectorAndSubSector([
      company({ company_id: 1, sector: 'banking', sub_sector: 'private_bank' }),
      company({ company_id: 2, sector: 'banking', sub_sector: 'psu_bank' }),
    ]);
    expect(sector.subSectorGroups.map((g) => g.label).sort()).toEqual(['PSU Bank', 'Private Bank']);
  });

  it('computes a net signal at both the sector and sub-sector level', () => {
    const [sector] = groupBySectorAndSubSector([
      company({ company_id: 1, sector: 'banking', sub_sector: 'private_bank', direction: 'bullish' }),
      company({ company_id: 2, sector: 'banking', sub_sector: 'private_bank', direction: 'bullish' }),
    ]);
    expect(sector.netSignal.direction).toBe('bullish');
    expect(sector.subSectorGroups[0].netSignal.direction).toBe('bullish');
  });
});
