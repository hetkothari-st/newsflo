import { useState } from 'react';
import type { CompanyGroup, GroupMode } from './transforms';
import ReasoningPanel from '../../components/ReasoningPanel';

const COL_WIDTH = 108;
const NODE_HEIGHT = 26;
const ROW_GAP = 8;
const LEVEL_GAP = 36;
const TOP_PADDING = 18;
const SIDE_PADDING = 12;

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
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

  const branchCount = groups.length;
  const maxLeaves = Math.max(1, ...groups.map((g) => g.companies.length));
  const width = branchCount * COL_WIDTH + SIDE_PADDING * 2;
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
          <text x={rootX} y={rootY} textAnchor="middle" dominantBaseline="middle" className="fill-muted text-[10px]">
            {truncate(articleTitle, 34)}
          </text>

          {groups.map((group, i) => {
            const branchX = SIDE_PADDING + i * COL_WIDTH + COL_WIDTH / 2;
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
                  x={branchX - COL_WIDTH / 2 + 4}
                  y={branchY - NODE_HEIGHT / 2}
                  width={COL_WIDTH - 8}
                  height={NODE_HEIGHT}
                  rx={6}
                  className={branchClass(groupMode, group)}
                  style={branchStyle(groupMode, group)}
                  strokeWidth={1.5}
                />
                <text
                  x={branchX}
                  y={branchY}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  className="fill-ink text-[10px] font-bold uppercase tracking-wide"
                >
                  {truncate(group.label, 12)} · {leafCount}
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
                        x={branchX - COL_WIDTH / 2 + 4}
                        y={leafY - NODE_HEIGHT / 2}
                        width={COL_WIDTH - 8}
                        height={NODE_HEIGHT}
                        rx={6}
                        className={`fill-surface ${isSelected ? 'stroke-ink' : 'stroke-hairline'}`}
                        strokeWidth={isSelected ? 2 : 1.5}
                      />
                      <text
                        x={branchX - COL_WIDTH / 2 + 12}
                        y={leafY}
                        dominantBaseline="middle"
                        className={bullish ? 'fill-bullish text-[11px]' : 'fill-bearish text-[11px]'}
                      >
                        {bullish ? '▲' : '▼'}
                      </text>
                      <text x={branchX - COL_WIDTH / 2 + 24} y={leafY} dominantBaseline="middle" className="fill-ink text-[10px]">
                        {truncate(company.ticker.replace(/\.NS$/, ''), 10)}
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
