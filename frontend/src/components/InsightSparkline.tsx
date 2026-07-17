import type { PricePoint } from '../lib/api';

const WIDTH = 480;
const HEIGHT = 40;
const PAD = 4;

export default function InsightSparkline({
  points,
  direction,
}: {
  points: PricePoint[];
  direction: string;
}) {
  if (points.length < 2) return null;

  const closes = points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;

  const coords = points.map((p, i) => {
    const x = (i / (points.length - 1)) * WIDTH;
    const y = HEIGHT - PAD - ((p.close - min) / range) * (HEIGHT - PAD * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const strokeClass = direction === 'bearish' ? 'stroke-bearish' : 'stroke-bullish';
  const firstY = coords[0].split(',')[1];

  return (
    <svg width="100%" height={HEIGHT} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none">
      <line
        x1={0}
        y1={firstY}
        x2={WIDTH}
        y2={firstY}
        className="stroke-hairline"
        strokeWidth={1}
        strokeDasharray="1,3"
      />
      <polyline points={coords.join(' ')} fill="none" className={strokeClass} strokeWidth={1.75} />
    </svg>
  );
}
