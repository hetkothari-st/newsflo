/* Chart datasets for the v4 charts page -- every dataset is derived
   from the story's REAL feed-v2 detail payload (layers, timeline,
   measured numbers). Nothing is invented: a chart whose dataset can't
   be built honestly is simply absent from the deck (the app-wide
   hide-no-data rule). The reference sheet's supply-chain chart is
   deliberately not built at all: supplier/customer relations exist in
   no honest payload. */
import type { AlertDetail, LayerRow, TimelineEntry } from '../../v3/api';

export interface ChartRow extends LayerRow {
  layerIndex: number;
  layerTitle: string;
  relationship: string;
  icon: string;
}

export function flattenRows(detail: AlertDetail): ChartRow[] {
  return detail.layers.flatMap((layer, layerIndex) =>
    layer.rows.map((row) => ({
      ...row,
      layerIndex,
      layerTitle: layer.title,
      relationship: layer.relationship,
      icon: layer.icon,
    })),
  );
}

export type ChartKind =
  | 'impactTree'
  | 'ripple'
  | 'levels'
  | 'intensity'
  | 'split'
  | 'timeline'
  | 'sectors'
  | 'economicChain'
  | 'knowledge';

export interface ChartMeta {
  kind: ChartKind;
  title: string;
  subtitle: string;
}

export const CHART_ORDER: ChartMeta[] = [
  { kind: 'impactTree', title: 'Impact tree', subtitle: 'Affected companies by impact tier' },
  { kind: 'ripple', title: 'Ripple graph', subtitle: 'How the impact radiates from the story' },
  { kind: 'levels', title: 'Multi-level impact', subtitle: 'Levels of decreasing influence' },
  { kind: 'intensity', title: 'Intensity ranking', subtitle: 'Companies by measured reaction intensity' },
  { kind: 'split', title: 'Winners / losers', subtitle: 'Positive and negative reactions, separated' },
  { kind: 'sectors', title: 'Sector tree', subtitle: 'Impact organised by sector' },
  { kind: 'timeline', title: 'Timeline', subtitle: 'Impact over successive horizons' },
  { kind: 'economicChain', title: 'Impact chain', subtitle: 'How the effect propagates over time' },
  { kind: 'knowledge', title: 'Knowledge map', subtitle: 'Everything this story touches, counted' },
];

export function intensityBand(row: ChartRow): 'High' | 'Moderate' | 'Low' | null {
  const score = row.intensity?.score;
  if (score == null) return null;
  return score >= 70 ? 'High' : score >= 40 ? 'Moderate' : 'Low';
}

/* Relationship -> level. DIRECT companies are level 1; every other
   relationship is a step further out, in layer order. */
export function levelOf(row: ChartRow): number {
  if (row.relationship === 'DIRECT') return 1;
  return Math.min(row.layerIndex + 1, 4) + (row.relationship === 'DIRECT' ? 0 : 1) - 1 || 2;
}

export function availableCharts(detail: AlertDetail): ChartMeta[] {
  const rows = flattenRows(detail);
  const measured = rows.filter((row) => row.excess_move_pct != null);
  const timeline: TimelineEntry[] = detail.timeline;
  const sectors = new Set(rows.map((row) => row.sector));
  const has: Record<ChartKind, boolean> = {
    impactTree: rows.length > 0,
    ripple: measured.length >= 3,
    levels: rows.length > 0 && detail.layers.length >= 2,
    intensity: rows.some((row) => row.intensity?.score != null),
    split:
      rows.some((row) => row.direction === 'bullish') &&
      rows.some((row) => row.direction === 'bearish'),
    sectors: sectors.size >= 2,
    timeline: timeline.length > 0,
    economicChain: timeline.length >= 2,
    knowledge: rows.length >= 3,
  };
  return CHART_ORDER.filter((meta) => has[meta.kind]);
}
