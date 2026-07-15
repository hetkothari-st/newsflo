import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
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

  it('shows a tooltip with the price and date of the nearest point on mouse move', () => {
    const points: PricePoint[] = [
      { date: '2026-07-13', close: 100 },
      { date: '2026-07-14', close: 105 },
      { date: '2026-07-15', close: 95 },
    ];
    const { container } = render(<PriceChart points={points} unavailableLabel="Chart unavailable" />);
    const svg = container.querySelector('svg')!;
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ left: 0, width: 300, top: 0, height: 100, right: 300, bottom: 100, x: 0, y: 0, toJSON: () => ({}) });

    fireEvent.mouseMove(svg, { clientX: 150 });

    expect(screen.getByTestId('chart-tooltip')).toHaveTextContent('105');
    expect(screen.getByTestId('chart-tooltip')).toHaveTextContent('Jul 14');
  });

  it('hides the tooltip when the pointer leaves the chart', () => {
    const points: PricePoint[] = [
      { date: '2026-07-13', close: 100 },
      { date: '2026-07-14', close: 105 },
    ];
    const { container } = render(<PriceChart points={points} unavailableLabel="Chart unavailable" />);
    const svg = container.querySelector('svg')!;
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ left: 0, width: 300, top: 0, height: 100, right: 300, bottom: 100, x: 0, y: 0, toJSON: () => ({}) });
    fireEvent.mouseMove(svg, { clientX: 150 });
    expect(screen.queryByTestId('chart-tooltip')).toBeInTheDocument();

    fireEvent.mouseLeave(svg);

    expect(screen.queryByTestId('chart-tooltip')).not.toBeInTheDocument();
  });

  it('shows the tooltip on touch move', () => {
    const points: PricePoint[] = [
      { date: '2026-07-13', close: 100 },
      { date: '2026-07-14', close: 105 },
    ];
    const { container } = render(<PriceChart points={points} unavailableLabel="Chart unavailable" />);
    const svg = container.querySelector('svg')!;
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ left: 0, width: 300, top: 0, height: 100, right: 300, bottom: 100, x: 0, y: 0, toJSON: () => ({}) });

    fireEvent.touchStart(svg, { touches: [{ clientX: 10 }] });

    expect(screen.getByTestId('chart-tooltip')).toHaveTextContent('100');
  });
});
