import { describe, expect, it } from 'vitest';
import { layoutPriceChart, nearestPointIndex } from './priceChartLayout';
import type { PricePoint } from '../../lib/api';

const points: PricePoint[] = [
  { date: '2026-01-01', close: 100 },
  { date: '2026-01-02', close: 105 },
  { date: '2026-01-03', close: 95 },
];

describe('layoutPriceChart', () => {
  it('returns null for fewer than 2 points', () => {
    expect(layoutPriceChart([], 100, 50)).toBeNull();
    expect(layoutPriceChart([points[0]], 100, 50)).toBeNull();
  });

  it('reports the min and max close', () => {
    const layout = layoutPriceChart(points, 100, 50);
    expect(layout?.min).toBe(95);
    expect(layout?.max).toBe(105);
  });

  it('places the first point at x=0 and the last at x=width', () => {
    const layout = layoutPriceChart(points, 100, 50);
    const coords = layout!.points;
    expect(coords[0].x).toBe(0);
    expect(coords[coords.length - 1].x).toBe(100);
  });

  it('places the highest close at y=0 (SVG top) and lowest at y=height', () => {
    const layout = layoutPriceChart(points, 100, 50);
    const highest = layout!.points[1]; // close: 105, the max
    const lowest = layout!.points[2]; // close: 95, the min
    expect(highest.y).toBe(0);
    expect(lowest.y).toBe(50);
  });

  it('renders a flat line at mid-height when all closes are equal', () => {
    const flat = [
      { date: '2026-01-01', close: 100 },
      { date: '2026-01-02', close: 100 },
    ];
    const layout = layoutPriceChart(flat, 100, 50);
    expect(layout!.points.every((p) => p.y === 25)).toBe(true);
  });

  it('marks bullish (last close >= first close) and bearish trend', () => {
    expect(layoutPriceChart(points, 100, 50)?.trend).toBe('bearish'); // 95 < 100
    const rising = [{ date: '2026-01-01', close: 100 }, { date: '2026-01-02', close: 110 }];
    expect(layoutPriceChart(rising, 100, 50)?.trend).toBe('bullish');
  });
});

describe('nearestPointIndex', () => {
  const coords = [{ x: 0, y: 10 }, { x: 50, y: 20 }, { x: 100, y: 30 }];

  it('returns the index of the closest point to x', () => {
    expect(nearestPointIndex(coords, 5)).toBe(0);
    expect(nearestPointIndex(coords, 48)).toBe(1);
    expect(nearestPointIndex(coords, 96)).toBe(2);
  });

  it('picks the earlier index on an exact tie', () => {
    expect(nearestPointIndex(coords, 25)).toBe(0);
  });

  it('clamps to the last index for an x beyond the final point', () => {
    expect(nearestPointIndex(coords, 500)).toBe(2);
  });

  it('clamps to the first index for a negative x', () => {
    expect(nearestPointIndex(coords, -50)).toBe(0);
  });

  it('returns 0 for an empty points array', () => {
    expect(nearestPointIndex([], 10)).toBe(0);
  });
});
