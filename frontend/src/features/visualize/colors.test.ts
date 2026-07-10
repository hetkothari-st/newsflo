import { describe, expect, it } from 'vitest';
import { sectorColor } from './colors';

describe('sectorColor', () => {
  it('returns the same color for the same sector every time', () => {
    expect(sectorColor('Technology')).toBe(sectorColor('Technology'));
  });

  it('returns a hex color string', () => {
    expect(sectorColor('Energy')).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });

  it('can return different colors for different sectors', () => {
    const colors = new Set(['Technology', 'Energy', 'Financials', 'Healthcare', 'Industrials'].map(sectorColor));
    expect(colors.size).toBeGreaterThan(1);
  });
});
