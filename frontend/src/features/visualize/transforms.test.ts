import { describe, expect, it } from 'vitest';
import { groupByTier, groupByImpact, groupBySector } from './transforms';
import type { AlertCompany } from '../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
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
