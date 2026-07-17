import { useState, type ReactNode } from 'react';
import type { NetSignal } from '../../transforms';
import { severityLabel } from '../../transforms';

function tintHex(hex: string, alphaHex: string): string | undefined {
  return hex.startsWith('#') && hex.length === 7 ? `${hex}${alphaHex}` : undefined;
}

export default function ImpactCard({
  label,
  color,
  signal,
  companyCount,
  defaultCollapsed = false,
  collapsed: collapsedProp,
  onToggle,
  onViewDetails,
  children,
}: {
  label: string;
  color: string;
  signal: NetSignal;
  companyCount: number;
  defaultCollapsed?: boolean;
  collapsed?: boolean;
  onToggle?: () => void;
  onViewDetails?: () => void;
  children: ReactNode;
}) {
  const [internalCollapsed, setInternalCollapsed] = useState(defaultCollapsed);
  const isControlled = collapsedProp !== undefined;
  const collapsed = isControlled ? collapsedProp : internalCollapsed;
  const handleHeaderClick = () => {
    if (isControlled) onToggle?.();
    else setInternalCollapsed((v) => !v);
  };

  const badgeTone = signal.direction === 'even' ? 'text-muted' : signal.direction === 'bullish' ? 'text-bullish' : 'text-bearish';
  const badgeBg = signal.direction === 'even' ? undefined : tintHex(signal.direction === 'bullish' ? '#3E9B5C' : '#E85D4C', '1F');

  return (
    <div
      className="flex min-w-0 flex-col gap-2.5 rounded-xl border border-hairline p-3.5 theme-light:border-transparent theme-light:shadow-neu-sm"
      style={{ backgroundColor: tintHex(color, '0D') ?? 'rgb(var(--color-surface))' }}
    >
      <button type="button" onClick={handleHeaderClick} aria-expanded={!collapsed} className="flex items-start gap-2.5 text-left">
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
      {!collapsed && (
        <div className="flex flex-col gap-1">
          {children}
          {onViewDetails && (
            <button type="button" onClick={onViewDetails} className="mt-1 self-end text-xs text-muted hover:text-ink">
              View Details →
            </button>
          )}
        </div>
      )}
    </div>
  );
}
