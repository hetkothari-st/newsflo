import type { PricePoint } from '../../lib/api';
import { layoutPriceChart } from './priceChartLayout';

const WIDTH = 300;
const HEIGHT = 100;
const PADDING_Y = 8; // keeps the line off the top/bottom edge of the viewBox

export default function PriceChart({
  points,
  unavailableLabel,
}: {
  points: PricePoint[];
  unavailableLabel: string;
}) {
  const layout = layoutPriceChart(points, WIDTH, HEIGHT - PADDING_Y * 2);
  if (!layout) {
    return <p className="text-xs text-muted">{unavailableLabel}</p>;
  }

  const strokeClass = layout.trend === 'bullish' ? 'stroke-bullish' : 'stroke-bearish';
  const polylinePoints = layout.points.map((p) => `${p.x},${p.y + PADDING_Y}`).join(' ');

  return (
    <svg
      role="img"
      aria-label={`Price chart, ${layout.trend}`}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="h-24 w-full"
    >
      <polyline points={polylinePoints} fill="none" strokeWidth={2} className={strokeClass} />
    </svg>
  );
}
