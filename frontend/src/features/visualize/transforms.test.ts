import { describe, expect, it } from 'vitest';
import { buildImpactTree, buildSectorTree } from './transforms';
import type { AlertCompany } from '../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN', in_my_holdings: false,
    ...overrides,
  };
}

describe('buildImpactTree', () => {
  it('splits companies into Bullish and Bearish branches', () => {
    const tree = buildImpactTree('Some event', [
      company({ company_id: 1, direction: 'bullish' }),
      company({ company_id: 2, direction: 'bearish' }),
    ]);
    expect(tree.label).toBe('Some event');
    expect(tree.children.map((b) => b.label)).toEqual(['Bullish', 'Bearish']);
    expect(tree.children[0].children).toHaveLength(1);
    expect(tree.children[1].children).toHaveLength(1);
  });

  it('omits a branch with zero companies rather than rendering it empty', () => {
    const tree = buildImpactTree('Some event', [company({ direction: 'bullish' })]);
    expect(tree.children.map((b) => b.label)).toEqual(['Bullish']);
  });

  it('excludes companies whose direction is neither bullish nor bearish', () => {
    const tree = buildImpactTree('Some event', [company({ direction: 'unknown' })]);
    expect(tree.children).toHaveLength(0);
  });

  it('excludes an unrecognized-direction company while still bucketing its bullish/bearish siblings', () => {
    const tree = buildImpactTree('Some event', [
      company({ company_id: 1, direction: 'bullish' }),
      company({ company_id: 2, direction: 'bearish' }),
      company({ company_id: 3, direction: 'unknown' }),
    ]);
    const bullish = tree.children.find((b) => b.label === 'Bullish');
    const bearish = tree.children.find((b) => b.label === 'Bearish');
    expect(bullish?.children).toHaveLength(1);
    expect(bearish?.children).toHaveLength(1);
    expect(tree.children).toHaveLength(2);
  });
});

describe('buildSectorTree', () => {
  it('groups companies by sector, alphabetically', () => {
    const tree = buildSectorTree('Some event', [
      company({ company_id: 1, sector: 'Financials' }),
      company({ company_id: 2, sector: 'Energy' }),
      company({ company_id: 3, sector: 'Energy' }),
    ]);
    expect(tree.children.map((b) => b.label)).toEqual(['Energy', 'Financials']);
    expect(tree.children[0].children).toHaveLength(2);
  });

  it('groups companies with no sector under "Other"', () => {
    const tree = buildSectorTree('Some event', [company({ sector: undefined })]);
    expect(tree.children.map((b) => b.label)).toEqual(['Other']);
  });

  it('groups companies with an empty or whitespace-only sector under "Other"', () => {
    const tree = buildSectorTree('Some event', [
      company({ company_id: 1, sector: '' }),
      company({ company_id: 2, sector: '   ' }),
    ]);
    expect(tree.children.map((b) => b.label)).toEqual(['Other']);
    expect(tree.children[0].children).toHaveLength(2);
  });
});
