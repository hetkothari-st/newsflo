import { describe, expect, it } from 'vitest';
import { formatMarketCap } from './directoryLiveCaps';

describe('formatMarketCap', () => {
  it('formats lakh-crore scale megacaps', () => {
    // Reliance-scale: ~₹17.9 lakh crore
    expect(formatMarketCap(17_90_000 * 1e7)).toBe('₹17.9L Cr');
  });

  it('keeps two decimals just above the lakh-crore boundary', () => {
    expect(formatMarketCap(1_23_000 * 1e7)).toBe('₹1.23L Cr');
  });

  it('formats plain crore values with Indian digit grouping', () => {
    expect(formatMarketCap(9_420 * 1e7)).toBe('₹9,420 Cr');
  });

  it('keeps one decimal for small caps', () => {
    expect(formatMarketCap(42.5 * 1e7)).toBe('₹42.5 Cr');
  });
});
