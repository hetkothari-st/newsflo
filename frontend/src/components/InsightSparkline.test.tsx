import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import InsightSparkline from './InsightSparkline';
import type { PricePoint } from '../lib/api';

const POINTS: PricePoint[] = [
  { date: '2026-06-17', close: 100 },
  { date: '2026-06-24', close: 105 },
  { date: '2026-07-01', close: 98 },
  { date: '2026-07-17', close: 112 },
];

describe('InsightSparkline', () => {
  it('renders an svg with one polyline point per price point', () => {
    const { container } = render(<InsightSparkline points={POINTS} direction="bullish" />);
    const polyline = container.querySelector('polyline');
    expect(polyline).not.toBeNull();
    const drawnPoints = polyline!.getAttribute('points')!.trim().split(/\s+/);
    expect(drawnPoints).toHaveLength(POINTS.length);
  });

  it('colors the line bullish-green for a bullish direction', () => {
    const { container } = render(<InsightSparkline points={POINTS} direction="bullish" />);
    expect(container.querySelector('polyline')).toHaveClass('stroke-bullish');
  });

  it('colors the line bearish-red for a bearish direction', () => {
    const { container } = render(<InsightSparkline points={POINTS} direction="bearish" />);
    expect(container.querySelector('polyline')).toHaveClass('stroke-bearish');
  });

  it('renders nothing when there are fewer than 2 points', () => {
    const { container } = render(<InsightSparkline points={[POINTS[0]]} direction="bullish" />);
    expect(container.querySelector('svg')).toBeNull();
  });

  it('renders nothing for an empty points array', () => {
    const { container } = render(<InsightSparkline points={[]} direction="bullish" />);
    expect(container.querySelector('svg')).toBeNull();
  });
});
