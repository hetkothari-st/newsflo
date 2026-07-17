import { useRef, useState } from 'react';
import type { PricePoint } from '../../lib/api';
import { layoutPriceChart, nearestPointIndex } from './priceChartLayout';

const WIDTH = 300;
const AXIS_WIDTH = 42; // reserved right-side margin for min/max price labels
const CHART_WIDTH = WIDTH - AXIS_WIDTH;
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
  const layout = layoutPriceChart(points, CHART_WIDTH, HEIGHT - PADDING_Y * 2);

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

  const midValue = (layout.max + layout.min) / 2;
  const axisLabelX = CHART_WIDTH + 5;
  const maxY = PADDING_Y;
  const midY = HEIGHT / 2;
  const minY = HEIGHT - PADDING_Y;

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
        <line x1={0} x2={CHART_WIDTH} y1={maxY} y2={maxY} className="stroke-hairline" strokeWidth={1} strokeDasharray="1,3" />
        <line x1={0} x2={CHART_WIDTH} y1={midY} y2={midY} className="stroke-hairline" strokeWidth={1} strokeDasharray="1,3" />
        <line x1={0} x2={CHART_WIDTH} y1={minY} y2={minY} className="stroke-hairline" strokeWidth={1} strokeDasharray="1,3" />
        <line x1={CHART_WIDTH} x2={CHART_WIDTH} y1={0} y2={HEIGHT} className="stroke-hairline" strokeWidth={1} />
        <text x={axisLabelX} y={maxY + 3} className="fill-muted text-[9px]">{layout.max.toFixed(0)}</text>
        <text x={axisLabelX} y={midY + 3} className="fill-muted text-[9px]">{midValue.toFixed(0)}</text>
        <text x={axisLabelX} y={minY + 3} className="fill-muted text-[9px]">{layout.min.toFixed(0)}</text>
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
