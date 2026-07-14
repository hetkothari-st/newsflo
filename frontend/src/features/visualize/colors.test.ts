import { describe, expect, it } from 'vitest';
import { sectorColor } from './colors';

describe('sectorColor', () => {
  it('assigns a fixed color to each known sector, not a hash', () => {
    expect(sectorColor('oil_gas')).toBe(sectorColor('oil_gas'));
    expect(sectorColor('banking')).not.toBe(sectorColor('oil_gas'));
  });

  it('returns a hex color string for every known sector', () => {
    const known = ['oil_gas', 'banking', 'auto', 'it', 'pharma', 'fmcg', 'metals', 'telecom', 'infra', 'other'];
    for (const sector of known) {
      expect(sectorColor(sector)).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it('assigns every known sector a distinct color', () => {
    const known = ['oil_gas', 'banking', 'auto', 'it', 'pharma', 'fmcg', 'metals', 'telecom', 'infra', 'other'];
    const colors = new Set(known.map(sectorColor));
    expect(colors.size).toBe(known.length);
  });

  it('falls back to a defined color for an unrecognized sector string', () => {
    expect(sectorColor('some_future_sector')).toMatch(/^#[0-9A-Fa-f]{6}$/);
    expect(sectorColor('some_future_sector')).toBe(sectorColor('another_unknown'));
  });
});
