import { useState, type ReactNode } from 'react';
import type { NetSignal } from '../../transforms';
import { severityLabel } from '../../transforms';

// Appends an alpha suffix to a 6-digit hex for a low-opacity tint -- see
// Tree.tsx's identical helper. Duplicated (not imported) because this lives
// in a sibling module with no shared "colors" utility file for this one
// two-line helper; both copies must stay in sync if the tint strategy ever
// changes.
function tintHex(hex: string, alphaHex: string): string | undefined {
  return hex.startsWith('#') && hex.length === 7 ? `${hex}${alphaHex}` : undefined;
}

// One card in the mockup's card-grid layout: colored swatch + label +
// severity badge header, optional one-line signal summary, then arbitrary
// content (company rows, nested cards). Used by every rebuilt chart
// (Sector, Levels, Confidence, Split, Timeline) so a "sector card" and a
// "confidence band card" and an "impact-level card" all read as the same
// visual family.
export default function ImpactCard({
  label,
  color,
  signal,
  companyCount,
  defaultCollapsed = false,
  children,
}: {
  label: string;
  color: string;
  signal: NetSignal;
  companyCount: number;
  defaultCollapsed?: boolean;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const badgeTone = signal.direction === 'even' ? 'text-muted' : signal.direction === 'bullish' ? 'text-bullish' : 'text-bearish';
  const badgeBg = signal.direction === 'even' ? undefined : tintHex(signal.direction === 'bullish' ? '#3E9B5C' : '#E85D4C', '1F');

  return (
    <div
      className="flex min-w-0 flex-col gap-2.5 rounded-xl border border-hairline p-3.5 theme-light:border-transparent theme-light:shadow-neu-sm"
      style={{ backgroundColor: tintHex(color, '0D') ?? 'rgb(var(--color-surface))' }}
    >
      <button type="button" onClick={() => setCollapsed((v) => !v)} aria-expanded={!collapsed} className="flex items-start gap-2.5 text-left">
        <span aria-hidden="true" className="mt-0.5 h-8 w-8 shrink-0 rounded-lg" style={{ backgroundColor: color }} />
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-ink">{label}</span>
            <span aria-hidden="true" className="ml-auto shrink-0 text-[10px] text-muted">
              {collapsed ? '▸' : '▾'}
            </span>
          </span>
          <span className="flex items-center gap-2 text-xs">
            <span className={`shrink-0 rounded-full px-2 py-0.5 font-medium uppercase tracking-wide ${badgeTone}`} style={{ backgroundColor: badgeBg }}>
              {severityLabel(signal)}
            </span>
            <span className="truncate text-muted">
              {companyCount} {companyCount === 1 ? 'company' : 'companies'} · avg {signal.avgConfidence}% confidence
            </span>
          </span>
        </span>
      </button>
      {!collapsed && <div className="flex flex-col gap-1">{children}</div>}
    </div>
  );
}
