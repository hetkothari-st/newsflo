import { describe, expect, it } from 'vitest';
import { confidenceDotCount, horizonGlyph, horizonLabel, impactLabel } from './insightMappings';

describe('confidenceDotCount', () => {
  it('is 0 at score 0', () => {
    expect(confidenceDotCount(0)).toBe(0);
  });

  it('rounds to the nearest dot', () => {
    expect(confidenceDotCount(20)).toBe(1);
    expect(confidenceDotCount(21)).toBe(1);
    expect(confidenceDotCount(84)).toBe(4);
  });

  it('is 5 at score 100', () => {
    expect(confidenceDotCount(100)).toBe(5);
  });
});

describe('horizonGlyph', () => {
  it('maps each horizon to a distinct glyph', () => {
    expect(horizonGlyph('Immediate')).toBe('●');
    expect(horizonGlyph('Short-Term')).toBe('◔');
    expect(horizonGlyph('Medium-Term')).toBe('◑');
    expect(horizonGlyph('Long-Term')).toBe('◯');
  });

  it('falls back to the medium glyph for an unrecognized value', () => {
    expect(horizonGlyph('unknown')).toBe('◑');
  });
});

describe('horizonLabel', () => {
  it('strips "-Term" from each horizon value', () => {
    expect(horizonLabel('Short-Term', 'en')).toBe('Short');
    expect(horizonLabel('Medium-Term', 'en')).toBe('Medium');
    expect(horizonLabel('Long-Term', 'en')).toBe('Long');
    expect(horizonLabel('Immediate', 'en')).toBe('Immediate');
  });
});

describe('impactLabel', () => {
  it('labels direct impact', () => {
    expect(impactLabel('direct', 'en')).toBe('Direct');
  });

  it('labels first-order indirect impact', () => {
    expect(impactLabel('indirect_l1', 'en')).toBe('Indirect');
  });

  it('labels second-order indirect impact distinctly', () => {
    expect(impactLabel('indirect_l2', 'en')).toBe('Indirect · 2nd-order');
  });

  it('defaults to direct when the level is undefined (legacy alerts)', () => {
    expect(impactLabel(undefined, 'en')).toBe('Direct');
  });
});
