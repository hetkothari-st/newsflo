/* Chart datasets for the v4 charts page -- every dataset is derived
   from the story's REAL feed-v2 detail payload (layers, timeline,
   measured numbers). Nothing is invented: a chart whose dataset can't
   be built honestly is simply absent from the deck (the app-wide
   hide-no-data rule). The reference sheet's supply-chain chart is
   deliberately not built at all: supplier/customer relations exist in
   no honest payload. */
import type { AlertDetail, LayerRow, TimelineEntry } from '../../v3/api';
// The ONE up/down/flat rule, shared with chartComponents.tsx's actual
// bucketing (finding I9). Availability and bucketing used to run two
// separate copies that disagreed, so the deck could offer a Winners /
// Losers tile whose columns then both rendered empty.
import { effectClass } from './effectRules';

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
  // Same thresholds as the backend's canonical bands (config.py
  // INTENSITY_BAND_HIGH=75 / _MODERATE=50) -- the chart legend previously
  // re-invented them at 70/40, showing a different band vocabulary than
  // the rest of the app for the same score.
  return score >= 75 ? 'High' : score >= 50 ? 'Moderate' : 'Low';
}

/* Is this row on the innermost (direct) level?

   Final-review finding I10: the deck tested `relationship === 'DIRECT'`
   literally, but that vocabulary is the LEGACY 3-tier generator's alone.
   A gated alert's sections emit `MECH:{label}` for its mechanism layers
   and `SECONDARY` for the outer one (see app.market.ripple_layers'
   strict path), so on every gated story -- the whole point of v4 -- NO
   row ever matched and the "Direct impact" level was silently empty
   while level-1 companies rendered a band out. `MECH:` layers ARE the
   direct level; `SECONDARY` is deliberately excluded, mapping to the
   indirect level like any other non-direct relationship.

   RippleLayer.relationship stays a plain string on purpose: the label
   half of `MECH:{label}` is server-authored free text, so the type can
   never be a closed union. */
export function isLevelOne(row: { relationship: string }): boolean {
  return row.relationship === 'DIRECT' || row.relationship.startsWith('MECH:');
}

/* Relationship -> level. Direct companies are level 1; every other
   relationship is a step further out, in layer order. */
export function levelOf(row: ChartRow): number {
  if (isLevelOne(row)) return 1;
  return Math.min(row.layerIndex + 1, 4) || 2;
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
    // Offered only when the SAME rule that buckets the chart actually
    // lands a row in each column -- effectClass requires a measured move,
    // so an exposure-only story no longer offers a tile that renders
    // "Positive impact · 0 / Negative impact · 0".
    split:
      rows.some((row) => effectClass(row) === 'up') &&
      rows.some((row) => effectClass(row) === 'down'),
    sectors: sectors.size >= 2,
    timeline: timeline.length > 0,
    economicChain: timeline.length >= 2,
    knowledge: rows.length >= 3,
  };
  return CHART_ORDER.filter((meta) => has[meta.kind]);
}
