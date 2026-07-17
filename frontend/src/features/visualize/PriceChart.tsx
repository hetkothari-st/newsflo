import { useRef, useState } from 'react';
import type { PricePoint } from '../../lib/api';
import { layoutPriceChart, nearestPointIndex } from './priceChartLayout';

const WIDTH = 320;
const AXIS_WIDTH = 52; // reserved right-side margin for comma-formatted price labels
const CHART_WIDTH = WIDTH - AXIS_WIDTH;
const HEIGHT = 120;
const PADDING_Y = 14; // keeps the line -- and the max/min axis labels -- off the top/bottom edge

function formatTooltipDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

function formatAxisPrice(value: number): string {
  return Math.round(value).toLocaleString();
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
  const axisLabelX = CHART_WIDTH + 8;
  const maxY = PADDING_Y;
  const midY = HEIGHT / 2;
  const minY = HEIGHT - PADDING_Y;
  const TICK_LENGTH = 4;

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        role="img"
        aria-label={`Price chart, ${layout.trend}`}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-32 w-full"
        onMouseMove={(e) => updateHoverFromClientX(e.clientX)}
        onMouseLeave={() => setHoverIndex(null)}
        onTouchStart={(e) => updateHoverFromClientX(e.touches[0].clientX)}
        onTouchMove={(e) => updateHoverFromClientX(e.touches[0].clientX)}
      >
        {[maxY, midY, minY].map((y) => (
          <line key={y} x1={0} x2={CHART_WIDTH} y1={y} y2={y} className="stroke-hairline" strokeWidth={1} />
        ))}
        <line x1={0} x2={0} y1={0} y2={HEIGHT} className="stroke-hairline" strokeWidth={1} />
        {[
          { y: maxY, value: layout.max },
          { y: midY, value: midValue },
          { y: minY, value: layout.min },
        ].map(({ y, value }) => (
          <g key={y}>
            <line x1={CHART_WIDTH} x2={CHART_WIDTH + TICK_LENGTH} y1={y} y2={y} className="stroke-hairline" strokeWidth={1} />
            <text
              x={axisLabelX}
              y={y}
              dominantBaseline="middle"
              className="font-data fill-muted text-[10px] tabular-nums"
            >
              {formatAxisPrice(value)}
            </text>
          </g>
        ))}
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
