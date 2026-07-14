import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import PriceChart from './PriceChart';
import type { PricePoint } from '../../lib/api';

describe('PriceChart', () => {
  it('shows an unavailable message when there are fewer than 2 points', () => {
    render(<PriceChart points={[]} unavailableLabel="Chart unavailable" />);
    expect(screen.getByText('Chart unavailable')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('renders an SVG line for 2+ points', () => {
    const points: PricePoint[] = [
      { date: '2026-01-01', close: 100 },
      { date: '2026-01-02', close: 105 },
    ];
    render(<PriceChart points={points} unavailableLabel="Chart unavailable" />);
    expect(screen.getByRole('img')).toBeInTheDocument();
  });

  it('colors a rising line with the bullish token', () => {
    const points: PricePoint[] = [
      { date: '2026-01-01', close: 100 },
      { date: '2026-01-02', close: 110 },
    ];
    const { container } = render(<PriceChart points={points} unavailableLabel="Chart unavailable" />);
    expect(container.querySelector('polyline')).toHaveClass('stroke-bullish');
  });

  it('colors a falling line with the bearish token', () => {
    const points: PricePoint[] = [
      { date: '2026-01-01', close: 100 },
      { date: '2026-01-02', close: 90 },
    ];
    const { container } = render(<PriceChart points={points} unavailableLabel="Chart unavailable" />);
    expect(container.querySelector('polyline')).toHaveClass('stroke-bearish');
  });
});
