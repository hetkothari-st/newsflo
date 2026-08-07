/* The v4 charts, rebuilt to mirror the reference sheet's layouts
   faithfully -- true tree diagrams with fan edges, level bands, elbow
   lists, sector columns -- in the broadsheet paper/ink language. Every
   node, edge and count derives from the story's real detail payload:
   edges connect the news event to the companies it demonstrably
   affected (never invented pairings between companies). */
import type { JSX } from 'react';
import type { AlertDetail } from '../../v3/api';
import { flattenRows, intensityBand, type ChartMeta, type ChartRow } from './chartsData';

function fmtPct(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

function moveClass(value: number | null | undefined): string {
  if (value == null) return 'flat';
  return value < 0 ? 'down' : 'up';
}

/* ---------- shared SVG pieces ---------- */

const NODE_W = 126;
const NODE_H = 48;
const H_GAP = 10;
const PER_ROW = 5;

function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

function SvgNode({ x, y, row }: { x: number; y: number; row: ChartRow }) {
  const cls = moveClass(row.excess_move_pct);
  return (
    <g>
      <rect className={`cn-box ${cls}`} x={x} y={y} width={NODE_W} height={NODE_H} rx={8} />
      <text className="cn-tk" x={x + 10} y={y + 16}>
        {row.ticker.split('.')[0].slice(0, 10)}
      </text>
      <text className="cn-nm" x={x + 10} y={y + 29}>
        {row.name.slice(0, 20)}
      </text>
      <text className={`cn-mv ${cls}`} x={x + 10} y={y + 42}>
        {row.excess_move_pct == null ? 'exposure' : fmtPct(row.excess_move_pct)}
      </text>
    </g>
  );
}

/* Lay out rows of nodes centered in a width; returns node positions and
   the total height consumed. */
function layoutRows(rows: ChartRow[], width: number, startY: number) {
  const positions: Array<{ row: ChartRow; x: number; y: number }> = [];
  const lines = chunk(rows, PER_ROW);
  let y = startY;
  for (const line of lines) {
    const lineWidth = line.length * NODE_W + (line.length - 1) * H_GAP;
    let x = (width - lineWidth) / 2;
    for (const row of line) {
      positions.push({ row, x, y });
      x += NODE_W + H_GAP;
    }
    y += NODE_H + 14;
  }
  return { positions, bottom: y - 14 + NODE_H * 0 + 0, height: y - startY - 14 + 0 };
}

export function ChartFrame({
  number,
  meta,
  detail,
  children,
}: {
  number: number;
  meta: ChartMeta;
  detail: AlertDetail;
  children: JSX.Element;
}) {
  return (
    <article className="cframe">
      <header className="cframe-head">
        <span className="cframe-no">{String(number).padStart(2, '0')}</span>
        <div>
          <h2 className="cframe-title">{meta.title}</h2>
          <p className="cframe-sub">{meta.subtitle}</p>
        </div>
      </header>
      <div className="cframe-news">
        <span className="cframe-newskicker">News</span>
        <span className="cframe-newshl">{detail.article.title}</span>
      </div>
      <div className="cframe-body">{children}</div>
      <footer className="cframe-legend">
        <span>
          <i className="lg-up" /> positive impact
        </span>
        <span>
          <i className="lg-down" /> negative impact
        </span>
        <span>
          <i className="lg-flat" /> exposure only
        </span>
      </footer>
    </article>
  );
}

/* 1 -- Impact tree: news root, tier bands, fan edges news->tier1 and
   tier-hub->next tier (reference chart 1). */
export function CImpactTree({ detail }: { detail: AlertDetail }) {
  const W = 680;
  const newsW = 300;
  const newsH = 46;
  const newsX = (W - newsW) / 2;
  let y = newsH + 40;
  const tiers: Array<{
    label: string;
    positions: Array<{ row: ChartRow; x: number; y: number }>;
    top: number;
    bottom: number;
  }> = [];
  detail.layers.forEach((layer, layerIndex) => {
    const rows = layer.rows.map((row) => ({
      ...row,
      layerIndex,
      layerTitle: layer.title,
      relationship: layer.relationship,
      icon: layer.icon,
    }));
    const labelY = y;
    const { positions } = layoutRows(rows, W, y + 18);
    const bottom = Math.max(...positions.map((p) => p.y)) + NODE_H;
    tiers.push({ label: layer.title, positions, top: labelY, bottom });
    y = bottom + 44;
  });
  const height = y - 10;
  return (
    <svg className="csvg" viewBox={`0 0 ${W} ${height}`} role="img" aria-label="Impact tree">
      <rect className="cn-news" x={newsX} y={4} width={newsW} height={newsH} rx={8} />
      <text className="cn-newskicker" x={newsX + 12} y={20}>
        NEWS
      </text>
      <text className="cn-newshl" x={newsX + 12} y={36}>
        {detail.article.title.slice(0, 40)}
      </text>
      {tiers.map((tier, index) => {
        const sourceY = index === 0 ? 4 + newsH : tiers[index - 1].bottom;
        const sourceX = W / 2;
        return (
          <g key={tier.label + index}>
            <text className="csvg-band" x={0} y={tier.top + 8}>
              {tier.label.toUpperCase().slice(0, 52)}
            </text>
            {tier.positions.map((p) => (
              <path
                key={`e-${p.row.ticker}`}
                className="csvg-edge"
                d={`M ${sourceX} ${sourceY} C ${sourceX} ${sourceY + 22}, ${p.x + NODE_W / 2} ${p.y - 20}, ${p.x + NODE_W / 2} ${p.y}`}
              />
            ))}
            {tier.positions.map((p) => (
              <SvgNode key={p.row.ticker} x={p.x} y={p.y} row={p.row} />
            ))}
          </g>
        );
      })}
    </svg>
  );
}

/* 2 -- Ripple graph: radial rings by reaction size (reference chart 2). */
export function CRipple({ detail }: { detail: AlertDetail }) {
  const rows = flattenRows(detail)
    .filter((row) => row.excess_move_pct != null)
    .sort((a, b) => Math.abs(b.excess_move_pct!) - Math.abs(a.excess_move_pct!));
  const size = 380;
  const cx = size / 2;
  const rings = [82, 128, 168];
  const third = Math.ceil(rows.length / 3) || 1;
  return (
    <svg className="cripple" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Ripple graph">
      {rings.map((r) => (
        <circle key={r} className="cripple-ring" cx={cx} cy={cx} r={r} />
      ))}
      {rows.map((row, i) => {
        const ring = rings[Math.min(Math.floor(i / third), 2)];
        const angle = (i / rows.length) * Math.PI * 2 - Math.PI / 2;
        const x = cx + ring * Math.cos(angle);
        const y = cx + ring * Math.sin(angle);
        const cls = moveClass(row.excess_move_pct);
        return (
          <g key={row.ticker}>
            <line className="cripple-spoke" x1={cx} y1={cx} x2={x} y2={y} />
            <circle className={`cripple-node ${cls}`} cx={x} cy={y} r={17} />
            <text className="cripple-tk" x={x} y={y - 1} textAnchor="middle">
              {row.ticker.split('.')[0].slice(0, 6)}
            </text>
            <text className={`cripple-mv ${cls}`} x={x} y={y + 9} textAnchor="middle">
              {fmtPct(row.excess_move_pct!)}
            </text>
          </g>
        );
      })}
      <circle className="cripple-hub" cx={cx} cy={cx} r={32} />
      <text className="cripple-hublabel" x={cx} y={cx + 3} textAnchor="middle">
        NEWS
      </text>
    </svg>
  );
}

/* 3 -- Multi-level impact: full-width level bands (reference chart 4). */
export function CLevels({ detail }: { detail: AlertDetail }) {
  const rows = flattenRows(detail);
  const levels = new Map<number, ChartRow[]>();
  for (const row of rows) {
    const level = row.relationship === 'DIRECT' ? 1 : row.layerIndex + 2;
    if (!levels.has(level)) levels.set(level, []);
    levels.get(level)!.push(row);
  }
  const ordered = [...levels.entries()].sort((a, b) => a[0] - b[0]);
  const labels = ['Direct impact', 'Indirect impact', 'Tertiary impact', 'Wider ecosystem'];
  return (
    <div className="clevels">
      {ordered.map(([level, levelRows], index) => (
        <div className="clevel" key={level}>
          <div className="clevel-label">
            <span>
              Level {index + 1} <em>({labels[Math.min(index, labels.length - 1)]})</em>
            </span>
            <em>{levelRows.length}</em>
          </div>
          <div className="clevel-grid">
            {levelRows.map((row) => (
              <div className={`cnode wide ${moveClass(row.excess_move_pct)}`} key={row.ticker}>
                <span className="cnode-tk">{row.ticker.split('.')[0]}</span>
                <span className="cnode-nm">{row.name}</span>
                <span className={`cnode-mv ${moveClass(row.excess_move_pct)}`}>
                  {row.excess_move_pct == null ? 'exposure' : fmtPct(row.excess_move_pct)}
                </span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/* 4 -- Intensity ranking with elbow connectors and a right-hand band
   axis (reference chart 5, kept honest: intensity is what this system
   measures). */
export function CIntensity({ detail }: { detail: AlertDetail }) {
  const rows = flattenRows(detail).filter((row) => row.intensity?.score != null);
  const bands: Array<['High' | 'Moderate' | 'Low', string]> = [
    ['High', '70–100'],
    ['Moderate', '40–69'],
    ['Low', '0–39'],
  ];
  return (
    <div className="cintensity">
      {bands.map(([band, range]) => {
        const bandRows = rows
          .filter((row) => intensityBand(row) === band)
          .sort((a, b) => b.intensity!.score - a.intensity!.score);
        if (bandRows.length === 0) return null;
        return (
          <div className="cint-band" key={band}>
            <div className="cint-main">
              <div className="cint-bandlabel">
                <span>{band} intensity</span>
              </div>
              {bandRows.map((row) => (
                <div className="cint-row" key={row.ticker}>
                  <span className="cnode-tk">{row.ticker.split('.')[0]}</span>
                  <span className="cnode-nm">{row.name}</span>
                  <span className={`cnode-mv ${moveClass(row.excess_move_pct)}`}>
                    {row.excess_move_pct == null ? '—' : fmtPct(row.excess_move_pct)}
                  </span>
                  <span className="cint-score">{row.intensity!.score}</span>
                </div>
              ))}
            </div>
            <div className="cint-axis">
              <span>
                {band}
                <br />
                {range}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* 5 -- Winners / losers split (reference chart 6). */
export function CSplit({ detail }: { detail: AlertDetail }) {
  const rows = flattenRows(detail);
  const winners = rows.filter((row) => row.direction === 'bullish' && row.excess_move_pct != null);
  const losers = rows.filter((row) => row.direction === 'bearish' && row.excess_move_pct != null);
  const neutral = rows.filter((row) => row.excess_move_pct == null);
  const col = (list: ChartRow[]) =>
    list.map((row) => (
      <div className={`cnode wide ${moveClass(row.excess_move_pct)}`} key={row.ticker}>
        <span className="cnode-tk">{row.ticker.split('.')[0]}</span>
        <span className="cnode-nm">{row.name}</span>
        <span className={`cnode-mv ${moveClass(row.excess_move_pct)}`}>
          {row.excess_move_pct == null ? 'exposure' : fmtPct(row.excess_move_pct)}
        </span>
      </div>
    ));
  return (
    <div className="csplit">
      <div className="csplit-cols">
        <div className="csplit-col up">
          <div className="csplit-collabel up">Positive impact · {winners.length}</div>
          {col(winners)}
        </div>
        <div className="csplit-col down">
          <div className="csplit-collabel down">Negative impact · {losers.length}</div>
          {col(losers)}
        </div>
      </div>
      {neutral.length > 0 && (
        <div className="csplit-neutral">
          <div className="csplit-collabel">Exposure only — no measured move · {neutral.length}</div>
          {col(neutral)}
        </div>
      )}
    </div>
  );
}

/* 6 -- Sector tree: news root, sector nodes, company columns with edges
   (reference chart 8). */
export function CSectors({ detail }: { detail: AlertDetail }) {
  const rows = flattenRows(detail);
  const bySector = new Map<string, ChartRow[]>();
  for (const row of rows) {
    if (!bySector.has(row.sector)) bySector.set(row.sector, []);
    bySector.get(row.sector)!.push(row);
  }
  const sectors = [...bySector.entries()].sort((a, b) => b[1].length - a[1].length).slice(0, 5);
  const colW = NODE_W + 18;
  const W = Math.max(560, sectors.length * colW);
  const newsW = 300;
  const newsX = (W - newsW) / 2;
  const sectorY = 96;
  const rowStep = NODE_H + 12;
  const maxLen = Math.max(...sectors.map(([, list]) => list.length));
  const height = sectorY + 40 + 26 + maxLen * rowStep + 4;
  return (
    <svg className="csvg" viewBox={`0 0 ${W} ${height}`} role="img" aria-label="Sector tree">
      <rect className="cn-news" x={newsX} y={4} width={newsW} height={46} rx={8} />
      <text className="cn-newskicker" x={newsX + 12} y={20}>
        NEWS
      </text>
      <text className="cn-newshl" x={newsX + 12} y={36}>
        {detail.article.title.slice(0, 40)}
      </text>
      {sectors.map(([sector, list], index) => {
        const colX = index * colW + (colW - NODE_W) / 2 + (W - sectors.length * colW) / 2;
        const cxCol = colX + NODE_W / 2;
        const measured = list.filter((row) => row.excess_move_pct != null);
        const avg =
          measured.length > 0
            ? measured.reduce((sum, row) => sum + row.excess_move_pct!, 0) / measured.length
            : null;
        return (
          <g key={sector}>
            <path
              className="csvg-edge"
              d={`M ${W / 2} 50 C ${W / 2} 72, ${cxCol} ${sectorY - 18}, ${cxCol} ${sectorY}`}
            />
            <rect className="cn-sector" x={colX} y={sectorY} width={NODE_W} height={40} rx={8} />
            <text className="cn-tk" x={colX + 10} y={sectorY + 17}>
              {sector.replace(/_/g, ' ').toUpperCase().slice(0, 14)}
            </text>
            {avg != null && (
              <text className={`cn-mv ${moveClass(avg)}`} x={colX + 10} y={sectorY + 32}>
                {fmtPct(avg)}
              </text>
            )}
            {list.length > 0 && (
              <line
                className="csvg-edge"
                x1={cxCol}
                y1={sectorY + 40}
                x2={cxCol}
                y2={sectorY + 40 + 26 + (list.length - 1) * rowStep}
              />
            )}
            {list.map((row, rowIndex) => (
              <SvgNode key={row.ticker} x={colX} y={sectorY + 40 + 26 + rowIndex * rowStep} row={row} />
            ))}
          </g>
        );
      })}
    </svg>
  );
}

/* 7 -- Timeline: horizon groups down a dotted spine (reference chart 7). */
export function CTimeline({ detail }: { detail: AlertDetail }) {
  return (
    <div className="ctl">
      {detail.timeline.map((entry, index) => (
        <div className="ctl-row" key={`${entry.horizon}-${index}`}>
          <div className="ctl-dotcol">
            <i className="ctl-dot" data-order={index % 4} />
            {index < detail.timeline.length - 1 && <span className="ctl-line" />}
          </div>
          <div className="ctl-card">
            <p className="ctl-h">{entry.horizon.replace(/_/g, ' ')}</p>
            <p className="ctl-d">{entry.description}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

/* 8 -- Impact chain (reference chart 9): the story propagating through
   its horizons into the measured market numbers. */
export function CEconomicChain({ detail }: { detail: AlertDetail }) {
  return (
    <div className="cchain">
      <div className="cchain-node news">
        <span className="cframe-newskicker">The story</span>
        <span>{detail.article.title}</span>
      </div>
      {detail.timeline.map((entry, index) => (
        <div className="cchain-step" key={`${entry.horizon}-${index}`}>
          <span className="cchain-arrow">↓</span>
          <div className="cchain-node">
            <span className="cchain-h">{entry.horizon.replace(/_/g, ' ')}</span>
            <span>{entry.description}</span>
          </div>
        </div>
      ))}
      <div className="cchain-step">
        <span className="cchain-arrow">↓</span>
        <div className="cchain-node market">
          <span className="cchain-h">Measured market impact</span>
          <span>
            Raw <b className={moveClass(detail.raw_move_pct)}>{fmtPct(detail.raw_move_pct)}</b>
            {'  ·  '}
            Sector{' '}
            <b className={moveClass(detail.sector_move_pct)}>{fmtPct(detail.sector_move_pct)}</b>
            {detail.volume_multiple != null && (
              <>
                {'  ·  '}Volume <b>{detail.volume_multiple.toFixed(1)}×</b>
              </>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}

/* 9 -- Knowledge map: hub with real relationship counts (reference
   chart 10). */
export function CKnowledge({ detail }: { detail: AlertDetail }) {
  const rows = flattenRows(detail);
  const sats = [
    { label: 'Winners', count: rows.filter((r) => r.direction === 'bullish' && r.excess_move_pct != null).length },
    { label: 'Losers', count: rows.filter((r) => r.direction === 'bearish' && r.excess_move_pct != null).length },
    { label: 'Exposure', count: rows.filter((r) => r.excess_move_pct == null).length },
    { label: 'Sectors', count: new Set(rows.map((r) => r.sector)).size },
    { label: 'Companies', count: rows.length },
    { label: 'Horizons', count: detail.timeline.length },
  ].filter((s) => s.count > 0);
  const size = 380;
  const cx = size / 2;
  const r = 136;
  return (
    <svg className="cknow" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Knowledge map">
      {sats.map((sat, i) => {
        const angle = (i / sats.length) * Math.PI * 2 - Math.PI / 2;
        const x = cx + r * Math.cos(angle);
        const y = cx + r * Math.sin(angle);
        return (
          <g key={sat.label}>
            <line className="cknow-spoke" x1={cx} y1={cx} x2={x} y2={y} />
            <circle className="cknow-node" cx={x} cy={y} r={31} />
            <text className="cknow-label" x={x} y={y - 3} textAnchor="middle">
              {sat.label}
            </text>
            <text className="cknow-count" x={x} y={y + 13} textAnchor="middle">
              ({sat.count})
            </text>
          </g>
        );
      })}
      <circle className="cknow-hub" cx={cx} cy={cx} r={46} />
      <text className="cknow-hublabel" x={cx} y={cx - 2} textAnchor="middle">
        News
      </text>
      <text className="cknow-hublabel" x={cx} y={cx + 12} textAnchor="middle">
        event
      </text>
    </svg>
  );
}
