import { useRef, useState } from 'react';
import type { PricePoint } from '../../lib/api';
import { layoutPriceChart, nearestPointIndex } from './priceChartLayout';

const WIDTH = 300;
const HEIGHT = 100;
const PADDING_Y = 8; // keeps the line off the top/bottom edge of the viewBox

function formatTooltipDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

export default function PriceChart({
  points,
  unavailableLabel,
}: {
  points: PricePoint[];
  unavailableLabel: string;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const layout = layoutPriceChart(points, WIDTH, HEIGHT - PADDING_Y * 2);

  if (!layout) {
    return <p className="text-xs text-muted">{unavailableLabel}</p>;
  }

  function updateHoverFromClientX(clientX: number) {
    const svg = svgRef.current;
    if (!svg || !layout) return;
    const rect = svg.getBoundingClientRect();
    const relativeX = ((clientX - rect.left) / rect.width) * WIDTH;
    setHoverIndex(nearestPointIndex(layout.points, relativeX));
  }

  const strokeClass = layout.trend === 'bullish' ? 'stroke-bullish' : 'stroke-bearish';
  const polylinePoints = layout.points.map((p) => `${p.x},${p.y + PADDING_Y}`).join(' ');
  const hovered = hoverIndex !== null ? { coord: layout.points[hoverIndex], point: points[hoverIndex] } : null;

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        role="img"
        aria-label={`Price chart, ${layout.trend}`}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-24 w-full"
        onMouseMove={(e) => updateHoverFromClientX(e.clientX)}
        onMouseLeave={() => setHoverIndex(null)}
        onTouchStart={(e) => updateHoverFromClientX(e.touches[0].clientX)}
        onTouchMove={(e) => updateHoverFromClientX(e.touches[0].clientX)}
      >
        <polyline points={polylinePoints} fill="none" strokeWidth={2} className={strokeClass} />
        {hovered && (
          <line
            x1={hovered.coord.x}
            x2={hovered.coord.x}
            y1={0}
            y2={HEIGHT}
            className="stroke-muted"
            strokeWidth={1}
            strokeDasharray="2,2"
          />
        )}
      </svg>
      {hovered && (
        <div
          data-testid="chart-tooltip"
          className="pointer-events-none absolute top-0 rounded-md border border-hairline bg-surface px-2 py-1 text-xs text-ink shadow-sm"
          style={{ left: `${(hovered.coord.x / WIDTH) * 100}%` }}
        >
          {formatTooltipDate(hovered.point.date)} · {hovered.point.close.toFixed(2)}
        </div>
      )}
    </div>
  );
}
