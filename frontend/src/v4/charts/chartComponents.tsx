/* The v4 charts, rebuilt to mirror the reference sheet's layouts
   faithfully -- true tree diagrams with fan edges, level bands, elbow
   lists, sector columns -- in the broadsheet paper/ink language. Every
   node, edge and count derives from the story's real detail payload:
   edges connect the news event to the companies it demonstrably
   affected (never invented pairings between companies). */
import { useEffect, useRef, useState, type JSX } from 'react';
import type { AlertDetail } from '../../v3/api';
import LogoV4 from '../LogoV4';
import { useLogo } from '../logoResolve';
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

/* Measured wrapper width -- charts lay themselves out to the space they
   actually have instead of a fixed canvas that gets cut on phones. */
function useMeasuredWidth(initial = 680): [React.RefObject<HTMLDivElement>, number] {
  const ref = useRef<HTMLDivElement>(null!);
  const [width, setWidth] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    setWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

function SvgNode({ x, y, row }: { x: number; y: number; row: ChartRow }) {
  const cls = moveClass(row.excess_move_pct);
  const resolved = useLogo(row.logo_url, row.ticker, row.name);
  const tx = x + 34;
  return (
    <g>
      <rect className={`cn-box ${cls}`} x={x} y={y} width={NODE_W} height={NODE_H} rx={8} />
      {resolved ? (
        <image
          href={resolved}
          x={x + 8}
          y={y + (NODE_H - 20) / 2}
          width={20}
          height={20}
          preserveAspectRatio="xMidYMid meet"
        />
      ) : (
        <>
          <rect className="cn-fb" x={x + 8} y={y + (NODE_H - 20) / 2} width={20} height={20} rx={6} />
          <text className="cn-fbtk" x={x + 18} y={y + NODE_H / 2 + 3} textAnchor="middle">
            {row.ticker.split('.')[0].slice(0, 2)}
          </text>
        </>
      )}
      <text className="cn-tk" x={tx} y={y + 16}>
        {row.ticker.split('.')[0].slice(0, 9)}
      </text>
      <text className="cn-nm" x={tx} y={y + 29}>
        {row.name.slice(0, 16)}
      </text>
      <text className={`cn-mv ${cls}`} x={tx} y={y + 42}>
        {row.excess_move_pct == null ? 'exposure' : fmtPct(row.excess_move_pct)}
      </text>
    </g>
  );
}

/* Lay out rows of nodes centered in a width; returns node positions and
   the total height consumed. */
function layoutRows(rows: ChartRow[], width: number, startY: number, perRow = PER_ROW) {
  const positions: Array<{ row: ChartRow; x: number; y: number }> = [];
  const lines = chunk(rows, perRow);
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
   tier-hub->next tier (reference chart 1). Lays out to the measured
   width -- nodes wrap into more rows on phones, nothing is cut. */
export function CImpactTree({ detail }: { detail: AlertDetail }) {
  const [wrapRef, measured] = useMeasuredWidth();
  const W = Math.max(300, Math.min(measured, 680));
  const perRow = Math.max(2, Math.floor((W + H_GAP) / (NODE_W + H_GAP)));
  const newsW = Math.min(300, W - 16);
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
    const { positions } = layoutRows(rows, W, y + 18, perRow);
    const bottom = Math.max(...positions.map((p) => p.y)) + NODE_H;
    tiers.push({ label: layer.title, positions, top: labelY, bottom });
    y = bottom + 44;
  });
  const height = y - 10;
  return (
    <div className="csvg-wrap" ref={wrapRef}>
      <svg
        className="csvg"
        width={W}
        height={height}
        viewBox={`0 0 ${W} ${height}`}
        role="img"
        aria-label="Impact tree"
      >
        <rect className="cn-news" x={newsX} y={4} width={newsW} height={newsH} rx={8} />
        <text className="cn-newskicker" x={newsX + 12} y={20}>
          NEWS
        </text>
        <text className="cn-newshl" x={newsX + 12} y={36}>
          {detail.article.title.slice(0, Math.floor(newsW / 7))}
        </text>
        {tiers.map((tier, index) => {
          const sourceY = index === 0 ? 4 + newsH : tiers[index - 1].bottom;
          const sourceX = W / 2;
          return (
            <g key={tier.label + index}>
              <text className="csvg-band" x={0} y={tier.top + 8}>
                {tier.label.toUpperCase()}
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
    </div>
  );
}

/* 2 -- Ripple graph (reference chart 2): a tiered NETWORK -- the news
   event on top, then each impact tier as a row of circle nodes fanning
   out beneath the one above. Tiers are the story's real layers; edges
   fan from the tier above (never invented company-to-company pairs). */
function RippleNode({ row, x, y }: { row: ChartRow; x: number; y: number }) {
  const cls = moveClass(row.excess_move_pct);
  const resolved = useLogo(row.logo_url, row.ticker, row.name);
  const clipId = `rip-${row.ticker.replace(/[^a-zA-Z0-9]/g, '')}`;
  return (
    <g>
      <circle className={`cripple-node ${cls}`} cx={x} cy={y} r={22} />
      {resolved ? (
        <>
          <clipPath id={clipId}>
            <circle cx={x} cy={y} r={18} />
          </clipPath>
          <image
            href={resolved}
            x={x - 15}
            y={y - 15}
            width={30}
            height={30}
            preserveAspectRatio="xMidYMid meet"
            clipPath={`url(#${clipId})`}
          />
        </>
      ) : (
        <text className="cripple-tk" x={x} y={y + 3} textAnchor="middle">
          {row.ticker.split('.')[0].slice(0, 2)}
        </text>
      )}
      <text className="cripple-tk" x={x} y={y + 35} textAnchor="middle">
        {row.ticker.split('.')[0].slice(0, 8)}
      </text>
      <text className={`cripple-mv ${cls}`} x={x} y={y + 46} textAnchor="middle">
        {row.excess_move_pct == null ? 'exposure' : fmtPct(row.excess_move_pct)}
      </text>
    </g>
  );
}

export function CRipple({ detail }: { detail: AlertDetail }) {
  const [wrapRef, measured] = useMeasuredWidth();
  const W = Math.max(300, Math.min(measured, 680));
  const CELL = 88;
  const perRow = Math.max(3, Math.floor(W / CELL));
  const ROW_H = 108;
  const newsY = 34;
  let y = newsY + 66;
  const tiers: Array<{ positions: Array<{ row: ChartRow; x: number; y: number }>; bottom: number }> = [];
  detail.layers.forEach((layer, layerIndex) => {
    const rows = layer.rows.map((row) => ({
      ...row,
      layerIndex,
      layerTitle: layer.title,
      relationship: layer.relationship,
      icon: layer.icon,
    }));
    const lines = chunk(rows, perRow);
    const positions: Array<{ row: ChartRow; x: number; y: number }> = [];
    for (const line of lines) {
      const lineWidth = line.length * CELL;
      let x = (W - lineWidth) / 2 + CELL / 2;
      for (const row of line) {
        positions.push({ row, x, y });
        x += CELL;
      }
      y += ROW_H;
    }
    tiers.push({ positions, bottom: y - ROW_H + 50 });
  });
  const height = y - ROW_H + 78;
  return (
    <div className="csvg-wrap" ref={wrapRef}>
      <svg
        className="cripple"
        width={W}
        height={height}
        viewBox={`0 0 ${W} ${height}`}
        role="img"
        aria-label="Ripple graph"
      >
        {tiers.map((tier, index) => {
          const sourceY = index === 0 ? newsY + 26 : tiers[index - 1].bottom;
          const sourceX = W / 2;
          return (
            <g key={index}>
              {tier.positions.map((p) => (
                <path
                  key={`e-${p.row.ticker}`}
                  className="cripple-spoke"
                  d={`M ${sourceX} ${sourceY} C ${sourceX} ${sourceY + 24}, ${p.x} ${p.y - 44}, ${p.x} ${p.y - 22}`}
                />
              ))}
            </g>
          );
        })}
        {tiers.map((tier, index) => (
          <g key={`n-${index}`}>
            {tier.positions.map((p) => (
              <RippleNode key={p.row.ticker} row={p.row} x={p.x} y={p.y} />
            ))}
          </g>
        ))}
        <circle className="cripple-hub" cx={W / 2} cy={newsY} r={26} />
        <text className="cripple-hublabel" x={W / 2} y={newsY + 3} textAnchor="middle">
          NEWS
        </text>
        <text className="cripple-newslabel" x={W / 2} y={newsY + 44} textAnchor="middle">
          News event
        </text>
      </svg>
    </div>
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
                <LogoV4 logoUrl={row.logo_url} ticker={row.ticker} name={row.name} />
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
                  <LogoV4 logoUrl={row.logo_url} ticker={row.ticker} name={row.name} />
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
        <LogoV4 logoUrl={row.logo_url} ticker={row.ticker} name={row.name} />
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

/* 6 -- Sector tree (reference chart 8), vertical tabular form: news
   root, then each sector as a header card with its companies on a
   connector spine beneath -- fits any width, nothing cut. */
export function CSectors({ detail }: { detail: AlertDetail }) {
  const rows = flattenRows(detail);
  const bySector = new Map<string, ChartRow[]>();
  for (const row of rows) {
    if (!bySector.has(row.sector)) bySector.set(row.sector, []);
    bySector.get(row.sector)!.push(row);
  }
  const sectors = [...bySector.entries()].sort((a, b) => b[1].length - a[1].length);
  return (
    <div className="cstree">
      <div className="cchain-node news">
        <span className="cframe-newskicker">News</span>
        <span>{detail.article.title}</span>
      </div>
      {sectors.map(([sector, list]) => {
        const measured = list.filter((row) => row.excess_move_pct != null);
        const avg =
          measured.length > 0
            ? measured.reduce((sum, row) => sum + row.excess_move_pct!, 0) / measured.length
            : null;
        return (
          <div className="cstree-sector" key={sector}>
            <span className="cstree-drop" aria-hidden="true" />
            <div className="cstree-shead">
              <span>{sector.replace(/_/g, ' ')}</span>
              <span className="cstree-scount">
                {list.length} {list.length === 1 ? 'company' : 'companies'}
              </span>
              {avg != null && <span className={`cnode-mv big ${moveClass(avg)}`}>{fmtPct(avg)}</span>}
            </div>
            <div className="cstree-list">
              {list.map((row) => (
                <div className={`cnode wide ${moveClass(row.excess_move_pct)}`} key={row.ticker}>
                  <LogoV4 logoUrl={row.logo_url} ticker={row.ticker} name={row.name} />
                  <span className="cnode-tk">{row.ticker.split('.')[0]}</span>
                  <span className="cnode-nm">{row.name}</span>
                  <span className={`cnode-mv ${moveClass(row.excess_move_pct)}`}>
                    {row.excess_move_pct == null ? 'exposure' : fmtPct(row.excess_move_pct)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
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

/* 8 -- Impact chain (reference chart 9): the shock propagating from
   the news through the sectors it actually hit, ordered by measured
   reaction size, ending in the market numbers -- a cause-and-effect
   chain, deliberately distinct from the timeline chart. */
export function CEconomicChain({ detail }: { detail: AlertDetail }) {
  const rows = flattenRows(detail);
  const bySector = new Map<string, ChartRow[]>();
  for (const row of rows) {
    if (row.excess_move_pct == null) continue;
    if (!bySector.has(row.sector)) bySector.set(row.sector, []);
    bySector.get(row.sector)!.push(row);
  }
  const sectors = [...bySector.entries()]
    .map(([sector, list]) => ({
      sector,
      avg: list.reduce((sum, row) => sum + row.excess_move_pct!, 0) / list.length,
      count: list.length,
    }))
    .sort((a, b) => Math.abs(b.avg) - Math.abs(a.avg));
  const stageLabel = (index: number) =>
    index === 0 ? 'Directly hit' : index === 1 ? 'First spillover' : 'Wider spillover';
  return (
    <div className="cchain">
      <div className="cchain-row">
        <div className="cchain-node news">
          <span className="cframe-newskicker">The story</span>
          <span>{detail.article.title}</span>
        </div>
        <span className="cchain-stage" />
      </div>
      {sectors.map((entry, index) => (
        <div className="cchain-row" key={entry.sector}>
          <div className="cchain-link" aria-hidden="true">
            ↓
          </div>
          <div className={`cchain-node sector ${moveClass(entry.avg)}`}>
            <span className="cchain-h">
              {entry.sector.replace(/_/g, ' ')} · {entry.count}{' '}
              {entry.count === 1 ? 'company' : 'companies'}
            </span>
            <span className={`cchain-big ${moveClass(entry.avg)}`}>
              {entry.avg < 0 ? '↓' : '↑'} {fmtPct(entry.avg)}
            </span>
          </div>
          <span className="cchain-stage">{stageLabel(index)}</span>
        </div>
      ))}
      <div className="cchain-row">
        <div className="cchain-link" aria-hidden="true">
          ↓
        </div>
        <div className="cchain-node market">
          <span className="cchain-h">Stock market impact</span>
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
        <span className="cchain-stage">Market</span>
      </div>
    </div>
  );
}

/* 9 -- Knowledge map: hub with real relationship counts; tapping a
   category blooms its members beside it (logos inside company member
   circles). Tap again to fold. */
interface KnowMember {
  label: string;
  sub: string;
  cls: string;
  logoUrl?: string | null;
  ticker?: string;
  name?: string;
}

function KnowMemberNode({ m, x, y }: { m: KnowMember; x: number; y: number }) {
  const resolved = useLogo(m.logoUrl, m.ticker ?? m.label, m.name);
  const clipId = `know-${(m.ticker ?? m.label).replace(/[^a-zA-Z0-9]/g, '')}`;
  const showLogo = Boolean(m.ticker) && Boolean(resolved);
  return (
    <g>
      <circle className={`cknow-member ${m.cls}`} cx={x} cy={y} r={24} />
      {showLogo ? (
        <>
          <clipPath id={clipId}>
            <circle cx={x} cy={y - 5} r={11} />
          </clipPath>
          <image
            href={resolved!}
            x={x - 10}
            y={y - 15}
            width={20}
            height={20}
            preserveAspectRatio="xMidYMid meet"
            clipPath={`url(#${clipId})`}
          />
          <text className="cknow-mlabel" x={x} y={y + 12} textAnchor="middle">
            {m.label}
          </text>
          {m.sub && (
            <text className={`cknow-msub ${m.cls}`} x={x} y={y + 20} textAnchor="middle">
              {m.sub}
            </text>
          )}
        </>
      ) : (
        <>
          <text className="cknow-mlabel" x={x} y={y + (m.sub ? -1 : 3)} textAnchor="middle">
            {m.label}
          </text>
          {m.sub && (
            <text className={`cknow-msub ${m.cls}`} x={x} y={y + 10} textAnchor="middle">
              {m.sub}
            </text>
          )}
        </>
      )}
    </g>
  );
}

export function CKnowledge({ detail }: { detail: AlertDetail }) {
  const [selected, setSelected] = useState<string | null>(null);
  const rows = flattenRows(detail);
  const winners = rows.filter((r) => r.direction === 'bullish' && r.excess_move_pct != null);
  const losers = rows.filter((r) => r.direction === 'bearish' && r.excess_move_pct != null);
  const exposure = rows.filter((r) => r.excess_move_pct == null);
  const sectors = [...new Set(rows.map((r) => r.sector))];
  const member = (row: ChartRow): KnowMember => ({
    label: row.ticker.split('.')[0].slice(0, 7),
    sub: row.excess_move_pct == null ? 'exp' : fmtPct(row.excess_move_pct),
    cls: moveClass(row.excess_move_pct),
    logoUrl: row.logo_url,
    ticker: row.ticker,
    name: row.name,
  });
  const sats: Array<{ label: string; members: KnowMember[] }> = [
    { label: 'Winners', members: winners.map(member) },
    { label: 'Losers', members: losers.map(member) },
    { label: 'Exposure', members: exposure.map(member) },
    {
      label: 'Sectors',
      members: sectors.map((sector) => ({
        label: sector.replace(/_/g, ' ').slice(0, 9),
        sub: '',
        cls: 'flat',
      })),
    },
    { label: 'Companies', members: rows.map(member) },
    {
      label: 'Horizons',
      members: detail.timeline.map((entry) => ({
        label: entry.horizon.replace(/_/g, ' ').slice(0, 9),
        sub: '',
        cls: 'flat',
      })),
    },
  ].filter((s) => s.members.length > 0);
  const size = 520;
  const cx = size / 2;
  const r = 140;
  return (
    <div className="csvg-wrap">
      <svg
        className="cknow"
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label="Knowledge map"
      >
        {sats.map((sat, i) => {
          const angle = (i / sats.length) * Math.PI * 2 - Math.PI / 2;
          const x = cx + r * Math.cos(angle);
          const y = cx + r * Math.sin(angle);
          const isSelected = selected === sat.label;
          return (
            <g key={sat.label}>
              <line className="cknow-spoke" x1={cx} y1={cx} x2={x} y2={y} />
              {isSelected &&
                sat.members.map((m, j) => {
                  const spread = Math.min(Math.PI * 1.1, 0.55 * sat.members.length);
                  const ma = angle - spread / 2 + (spread * j) / Math.max(1, sat.members.length - 1 || 1);
                  const mr = 88;
                  const mx = Math.min(size - 30, Math.max(30, x + mr * Math.cos(ma)));
                  const my = Math.min(size - 30, Math.max(30, y + mr * Math.sin(ma)));
                  return (
                    <g key={m.label + j}>
                      <line className="cknow-spoke" x1={x} y1={y} x2={mx} y2={my} />
                      <KnowMemberNode m={m} x={mx} y={my} />
                    </g>
                  );
                })}
              <g
                className="cknow-sat"
                onClick={() => setSelected(isSelected ? null : sat.label)}
                role="button"
                aria-label={`${sat.label}: ${sat.members.length}`}
              >
                <circle className={`cknow-node ${isSelected ? 'on' : ''}`} cx={x} cy={y} r={31} />
                <text className={`cknow-label ${isSelected ? 'on' : ''}`} x={x} y={y - 3} textAnchor="middle">
                  {sat.label}
                </text>
                <text className={`cknow-count ${isSelected ? 'on' : ''}`} x={x} y={y + 13} textAnchor="middle">
                  ({sat.members.length})
                </text>
              </g>
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
      <p className="cknow-hint">Tap a circle to unfold its members.</p>
    </div>
  );
}
