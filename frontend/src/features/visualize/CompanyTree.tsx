import { useState } from 'react';
import type { CompanyGroup, GroupMode } from './transforms';
import ReasoningPanel from '../../components/ReasoningPanel';

const NODE_HEIGHT = 28;
const ROW_GAP = 8;
const COL_GAP = 12;
const LEVEL_GAP = 36;
const TOP_PADDING = 18;
const SIDE_PADDING = 12;
const NODE_H_PADDING = 12;
const MIN_COL_WIDTH = 92;
const MAX_COL_WIDTH = 200;
const BRANCH_FONT = 'bold 11px -apple-system, BlinkMacSystemFont, Inter, sans-serif';
const LEAF_FONT = '11px -apple-system, BlinkMacSystemFont, Inter, sans-serif';

// Real text metrics when a canvas 2D context is available (every real
// browser); a per-character estimate in jsdom (its test environment) --
// so column widths always fit their actual label instead of a fixed guess
// that clips longer names like "Nifty Smallcap 250". jsdom's own canvas
// getContext('2d') isn't implemented and logs a console error on every
// call, so this checks jsdom's own userAgent marker to skip the call
// entirely there rather than calling it and swallowing the warning.
const CANVAS_MEASUREMENT_AVAILABLE =
  typeof navigator !== 'undefined' && !navigator.userAgent.includes('jsdom');
let measureCanvas: HTMLCanvasElement | null = null;
function textWidth(text: string, font: string): number {
  if (!CANVAS_MEASUREMENT_AVAILABLE) return text.length * 6.5;
  measureCanvas ??= document.createElement('canvas');
  const ctx = measureCanvas.getContext('2d');
  if (!ctx) return text.length * 6.5;
  ctx.font = font;
  return ctx.measureText(text).width;
}

function branchLabel(group: CompanyGroup): string {
  return `${group.label} · ${group.companies.length}`;
}

function leafLabel(ticker: string): string {
  return ticker.replace(/\.NS$/, '');
}

function columnWidth(group: CompanyGroup): number {
  const branchWidth = textWidth(branchLabel(group), BRANCH_FONT);
  const leafWidth = Math.max(0, ...group.companies.map((c) => textWidth(leafLabel(c.ticker), LEAF_FONT)));
  const needed = Math.max(branchWidth, leafWidth + 18) + NODE_H_PADDING * 2;
  return Math.min(MAX_COL_WIDTH, Math.max(MIN_COL_WIDTH, needed));
}

function branchClass(mode: GroupMode, group: CompanyGroup): string {
  if (mode === 'impact') return group.key === 'bullish' ? 'fill-bullish/15 stroke-bullish' : 'fill-bearish/15 stroke-bearish';
  if (group.color) return '';
  return 'fill-surface stroke-hairline';
}

function branchStyle(mode: GroupMode, group: CompanyGroup): { fill?: string; stroke?: string } | undefined {
  if (mode !== 'impact' && group.color) return { fill: `${group.color}26`, stroke: group.color };
  return undefined;
}

export default function CompanyTree({
  articleTitle,
  groups,
  groupMode,
}: {
  articleTitle: string;
  groups: CompanyGroup[];
  groupMode: GroupMode;
}) {
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const colWidths = groups.map(columnWidth);
  const colStarts = colWidths.reduce<number[]>((acc, _, i) => {
    acc.push(i === 0 ? SIDE_PADDING : acc[i - 1] + colWidths[i - 1] + COL_GAP);
    return acc;
  }, []);
  const width = colStarts.length > 0
    ? colStarts[colStarts.length - 1] + colWidths[colWidths.length - 1] + SIDE_PADDING
    : SIDE_PADDING * 2;

  const maxLeaves = Math.max(1, ...groups.map((g) => g.companies.length));
  const branchY = TOP_PADDING + NODE_HEIGHT / 2 + LEVEL_GAP;
  const firstLeafY = branchY + NODE_HEIGHT / 2 + LEVEL_GAP;
  const height = firstLeafY + maxLeaves * (NODE_HEIGHT + ROW_GAP) + TOP_PADDING;

  const rootX = width / 2;
  const rootY = TOP_PADDING + NODE_HEIGHT / 2;

  const selected = groups.flatMap((g) => g.companies).find((c) => c.company_id === selectedId) ?? null;

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto">
        <svg width={width} height={height} role="group" aria-label={`${articleTitle} ${groupMode} tree`}>
          <text x={rootX} y={rootY} textAnchor="middle" dominantBaseline="middle" className="fill-muted text-[11px]">
            {articleTitle.length > 40 ? `${articleTitle.slice(0, 39)}…` : articleTitle}
          </text>

          {groups.map((group, i) => {
            const colWidth = colWidths[i];
            const branchX = colStarts[i] + colWidth / 2;
            const leafCount = group.companies.length;
            const lastLeafY = firstLeafY + (leafCount - 1) * (NODE_HEIGHT + ROW_GAP);

            return (
              <g key={group.key}>
                <line
                  x1={rootX}
                  y1={rootY + NODE_HEIGHT / 2}
                  x2={branchX}
                  y2={branchY - NODE_HEIGHT / 2}
                  className="stroke-hairline"
                  strokeWidth={1.5}
                />
                {leafCount > 0 && (
                  <line
                    x1={branchX}
                    y1={branchY + NODE_HEIGHT / 2}
                    x2={branchX}
                    y2={lastLeafY}
                    className="stroke-hairline"
                    strokeWidth={1.5}
                  />
                )}

                <rect
                  x={colStarts[i]}
                  y={branchY - NODE_HEIGHT / 2}
                  width={colWidth}
                  height={NODE_HEIGHT}
                  rx={7}
                  className={branchClass(groupMode, group)}
                  style={branchStyle(groupMode, group)}
                  strokeWidth={1.5}
                />
                <text
                  x={branchX}
                  y={branchY}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  className="fill-ink text-[11px] font-bold"
                >
                  {branchLabel(group)}
                </text>

                {group.companies.map((company, j) => {
                  const leafY = firstLeafY + j * (NODE_HEIGHT + ROW_GAP);
                  const bullish = company.direction === 'bullish';
                  const isSelected = company.company_id === selectedId;
                  return (
                    <g
                      key={company.company_id}
                      role="button"
                      tabIndex={0}
                      aria-label={`${company.name} (${company.ticker})`}
                      onClick={() => setSelectedId(company.company_id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          setSelectedId(company.company_id);
                        }
                      }}
                      className="cursor-pointer"
                    >
                      <rect
                        x={colStarts[i]}
                        y={leafY - NODE_HEIGHT / 2}
                        width={colWidth}
                        height={NODE_HEIGHT}
                        rx={7}
                        className={`fill-surface ${isSelected ? 'stroke-ink' : 'stroke-hairline'}`}
                        strokeWidth={isSelected ? 2 : 1.5}
                      />
                      <text
                        x={colStarts[i] + NODE_H_PADDING}
                        y={leafY}
                        dominantBaseline="middle"
                        className={bullish ? 'fill-bullish text-[12px]' : 'fill-bearish text-[12px]'}
                      >
                        {bullish ? '▲' : '▼'}
                      </text>
                      <text
                        x={colStarts[i] + NODE_H_PADDING + 16}
                        y={leafY}
                        dominantBaseline="middle"
                        className="fill-ink text-[11px]"
                      >
                        {leafLabel(company.ticker)}
                      </text>
                    </g>
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>
      {selected && <ReasoningPanel company={selected} />}
    </div>
  );
}
