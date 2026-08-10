import { describe, expect, it } from 'vitest';
import { fmtMarketCapCr, fmtRatio } from './format';

describe('fmtMarketCapCr', () => {
  it('renders a dash for null', () => {
    expect(fmtMarketCapCr(null)).toBe('—');
  });

  it('converts absolute rupees to en-IN grouped crore', () => {
    // 17,662,582,622,436 rupees = 17,66,258 crore (rounded).
    expect(fmtMarketCapCr(17_662_582_622_436)).toBe('₹17,66,258 Cr');
    expect(fmtMarketCapCr(10_000_000)).toBe('₹1 Cr');
  });
});

describe('fmtRatio', () => {
  it('renders a dash for null, one decimal otherwise', () => {
    expect(fmtRatio(null)).toBe('—');
    expect(fmtRatio(9.52)).toBe('9.5');
    expect(fmtRatio(-8.4)).toBe('-8.4');
  });
});
