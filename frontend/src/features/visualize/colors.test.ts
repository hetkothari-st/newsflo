import { describe, expect, it } from 'vitest';
import { confidenceColor, confidenceBandColor, sectorColor } from './colors';

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

describe('confidenceColor', () => {
  it('returns a hex color string for any score 0-100', () => {
    for (const score of [0, 20, 40, 55, 80, 100]) {
      expect(confidenceColor(score)).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it('is monotonic: higher scores map to later (darker) ramp steps, never an earlier one', () => {
    const RAMP_ORDER = ['#6F9EE4', '#5C8ACE', '#4976B9', '#3763A4', '#25508F'];
    let lastIndex = -1;
    for (const score of [0, 25, 50, 75, 100]) {
      const idx = RAMP_ORDER.indexOf(confidenceColor(score));
      expect(idx).toBeGreaterThanOrEqual(lastIndex);
      lastIndex = idx;
    }
  });
});

describe('confidenceBandColor', () => {
  it('returns a hex color string for every known band', () => {
    for (const band of ['LOW', 'MODERATE', 'HIGH', 'VERY_HIGH']) {
      expect(confidenceBandColor(band)).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it('is monotonic: LOW < MODERATE < HIGH < VERY_HIGH on the same ramp', () => {
    const RAMP_ORDER = ['#6F9EE4', '#5C8ACE', '#4976B9', '#3763A4', '#25508F'];
    const indices = ['LOW', 'MODERATE', 'HIGH', 'VERY_HIGH'].map((band) =>
      RAMP_ORDER.indexOf(confidenceBandColor(band)),
    );
    for (let i = 1; i < indices.length; i++) {
      expect(indices[i]).toBeGreaterThan(indices[i - 1]);
    }
  });

  it('falls back to the MODERATE color for an unrecognized band string', () => {
    expect(confidenceBandColor('not_a_real_band')).toBe(confidenceBandColor('MODERATE'));
  });
});
