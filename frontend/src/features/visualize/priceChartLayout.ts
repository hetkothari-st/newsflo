import type { PricePoint } from '../../lib/api';

export interface ChartCoord {
  x: number;
  y: number;
}

export interface PriceChartLayout {
  points: ChartCoord[];
  min: number;
  max: number;
  trend: 'bullish' | 'bearish';
}

// Pure geometry only -- no DOM/React -- so it's testable without jsdom (see
// CompanyTree.tsx's text-measurement pain for why that separation matters).
export function layoutPriceChart(points: PricePoint[], width: number, height: number): PriceChartLayout | null {
  if (points.length < 2) return null;

  const closes = points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min;

  const coords = points.map((p, i) => ({
    x: (i / (points.length - 1)) * width,
    y: range === 0 ? height / 2 : height - ((p.close - min) / range) * height,
  }));

  return {
    points: coords,
    min,
    max,
    trend: closes[closes.length - 1] >= closes[0] ? 'bullish' : 'bearish',
  };
}
