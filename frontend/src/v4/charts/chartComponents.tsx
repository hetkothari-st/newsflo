/* The nine v4 charts, built from scratch to the reference sheet's
   layouts in the broadsheet paper/ink language. Every node, number and
   count comes from the story's real detail payload (see chartsData.ts)
   -- no invented companies, no invented values. */
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

function Node({ row, wide = false }: { row: ChartRow; wide?: boolean }) {
  return (
    <div className={`cnode ${moveClass(row.excess_move_pct)} ${wide ? 'wide' : ''}`}>
      <span className="cnode-tk">{row.ticker.split('.')[0]}</span>
      <span className="cnode-nm">{row.name}</span>
      <span className={`cnode-mv ${moveClass(row.excess_move_pct)}`}>
        {row.excess_move_pct == null ? 'exposure' : fmtPct(row.excess_move_pct)}
      </span>
    </div>
  );
}

export function ChartFrame({
  number,
  meta,
  detail,
  legend,
  children,
}: {
  number: number;
  meta: ChartMeta;
  detail: AlertDetail;
  legend?: JSX.Element;
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
      {legend ?? (
        <footer className="cframe-legend">
          <span>
            <i className="lg-up" /> positive
          </span>
          <span>
            <i className="lg-down" /> negative
          </span>
          <span>
            <i className="lg-flat" /> exposure only
          </span>
        </footer>
      )}
    </article>
  );
}

/* 1 -- Impact tree: the story's layers as tiers, top-down. */
export function CImpactTree({ detail }: { detail: AlertDetail }) {
  return (
    <div className="ctree">
      {detail.layers.map((layer, index) => (
        <div className="ctree-tier" key={`${layer.title}-${index}`}>
          <div className="ctree-band">
            <span>{layer.title}</span>
          </div>
          <div className="ctree-rows">
            {layer.rows.map((row) => (
              <Node
                key={row.ticker}
                row={{ ...row, layerIndex: index, layerTitle: layer.title, relationship: layer.relationship, icon: layer.icon }}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/* 2 -- Ripple graph: measured companies in rings by reaction size. */
export function CRipple({ detail }: { detail: AlertDetail }) {
  const rows = flattenRows(detail)
    .filter((row) => row.excess_move_pct != null)
    .sort((a, b) => Math.abs(b.excess_move_pct!) - Math.abs(a.excess_move_pct!));
  const size = 360;
  const cx = size / 2;
  const rings = [78, 122, 162];
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
            <circle className={`cripple-node ${cls}`} cx={x} cy={y} r={15} />
            <text className="cripple-tk" x={x} y={y - 1} textAnchor="middle">
              {row.ticker.split('.')[0].slice(0, 6)}
            </text>
            <text className={`cripple-mv ${cls}`} x={x} y={y + 9} textAnchor="middle">
              {fmtPct(row.excess_move_pct!)}
            </text>
          </g>
        );
      })}
      <circle className="cripple-hub" cx={cx} cy={cx} r={30} />
      <text className="cripple-hublabel" x={cx} y={cx + 3} textAnchor="middle">
        NEWS
      </text>
    </svg>
  );
}

/* 3 -- Multi-level impact: levels of decreasing influence. */
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
            Level {index + 1} <em>({labels[Math.min(index, labels.length - 1)]})</em>
          </div>
          <div className="ctree-rows">
            {levelRows.map((row) => (
              <Node key={row.ticker} row={row} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/* 4 -- Intensity ranking (the reference's confidence tree, kept honest:
   intensity is the score this system actually measures). */
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
            <div className="cint-bandlabel">
              <span>{band} intensity</span>
              <em>{range}</em>
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
        );
      })}
    </div>
  );
}

/* 5 -- Winners / losers split, exposure-only as the neutral strip. */
export function CSplit({ detail }: { detail: AlertDetail }) {
  const rows = flattenRows(detail);
  const winners = rows.filter((row) => row.direction === 'bullish' && row.excess_move_pct != null);
  const losers = rows.filter((row) => row.direction === 'bearish' && row.excess_move_pct != null);
  const neutral = rows.filter((row) => row.excess_move_pct == null);
  return (
    <div className="csplit">
      <div className="csplit-cols">
        <div className="csplit-col up">
          <div className="csplit-collabel up">Positive impact</div>
          {winners.map((row) => (
            <Node key={row.ticker} row={row} wide />
          ))}
        </div>
        <div className="csplit-col down">
          <div className="csplit-collabel down">Negative impact</div>
          {losers.map((row) => (
            <Node key={row.ticker} row={row} wide />
          ))}
        </div>
      </div>
      {neutral.length > 0 && (
        <div className="csplit-neutral">
          <div className="csplit-collabel">Exposure only — no measured move</div>
          {neutral.map((row) => (
            <Node key={row.ticker} row={row} wide />
          ))}
        </div>
      )}
    </div>
  );
}

/* 6 -- Sector tree: impact organised by sector. */
export function CSectors({ detail }: { detail: AlertDetail }) {
  const rows = flattenRows(detail);
  const yes = new Map<string, ChartRow[]>();
  for (const row of rows) {
    if (!yes.has(row.sector)) yes.set(row.sector, []);
    yes.get(row.sector)!.push(row);
  }
  const sectors = [...yes.entries()].sort((a, b) => b[1].length - a[1].length);
  return (
    <div className="csectors">
      {sectors.map(([sector, sectorRows]) => {
        const measured = sectorRows.filter((row) => row.excess_move_pct != null);
        const avg =
          measured.length > 0
            ? measured.reduce((sum, row) => sum + row.excess_move_pct!, 0) / measured.length
            : null;
        return (
          <div className="csector" key={sector}>
            <div className="csector-head">
              <span>{sector.replace(/_/g, ' ')}</span>
              {avg != null && <span className={`cnode-mv ${moveClass(avg)}`}>{fmtPct(avg)}</span>}
            </div>
            {sectorRows.map((row) => (
              <Node key={row.ticker} row={row} wide />
            ))}
          </div>
        );
      })}
    </div>
  );
}

/* 7 -- Timeline: the story's real horizon entries. */
export function CTimeline({ detail }: { detail: AlertDetail }) {
  return (
    <div className="ctl">
      {detail.timeline.map((entry, index) => (
        <div className="ctl-row" key={`${entry.horizon}-${index}`}>
          <div className="ctl-dotcol">
            <i className="ctl-dot" />
            {index < detail.timeline.length - 1 && <span className="ctl-line" />}
          </div>
          <div>
            <p className="ctl-h">{entry.horizon.replace(/_/g, ' ')}</p>
            <p className="ctl-d">{entry.description}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

/* 8 -- Impact chain: the story propagating through its horizons into
   the measured market numbers. */
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
            Sector <b className={moveClass(detail.sector_move_pct)}>{fmtPct(detail.sector_move_pct)}</b>
            {detail.volume_multiple != null && <>{'  ·  '}Volume <b>{detail.volume_multiple.toFixed(1)}×</b></>}
          </span>
        </div>
      </div>
    </div>
  );
}

/* 9 -- Knowledge map: real counts of everything the story touches. */
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
  const size = 360;
  const cx = size / 2;
  const r = 130;
  return (
    <svg className="cknow" viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Knowledge map">
      {sats.map((sat, i) => {
        const angle = (i / sats.length) * Math.PI * 2 - Math.PI / 2;
        const x = cx + r * Math.cos(angle);
        const y = cx + r * Math.sin(angle);
        return (
          <g key={sat.label}>
            <line className="cknow-spoke" x1={cx} y1={cx} x2={x} y2={y} />
            <circle className="cknow-node" cx={x} cy={y} r={30} />
            <text className="cknow-label" x={x} y={y - 3} textAnchor="middle">
              {sat.label}
            </text>
            <text className="cknow-count" x={x} y={y + 12} textAnchor="middle">
              {sat.count}
            </text>
          </g>
        );
      })}
      <circle className="cknow-hub" cx={cx} cy={cx} r={44} />
      <text className="cknow-hublabel" x={cx} y={cx - 2} textAnchor="middle">
        This
      </text>
      <text className="cknow-hublabel" x={cx} y={cx + 12} textAnchor="middle">
        story
      </text>
    </svg>
  );
}
