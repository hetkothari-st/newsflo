import { useState, type CSSProperties, type ReactNode } from 'react';

export function TreeRoot({ children }: { children: ReactNode }) {
  return <ul className="flex flex-col gap-3">{children}</ul>;
}

// Appends an alpha suffix to a 6-digit hex color for a low-opacity tint --
// e.g. tintHex('#4A90D9', '14') -- rather than a separate rgba palette, so
// every branch card reuses the exact same validated hue at reduced strength.
// Only safe for the #RRGGBB hexes this app's color modules already emit
// (SECTOR_COLOR, confidenceBandColor, IMPACT_LEVEL_COLOR) -- not for
// arbitrary CSS color strings like rgb(var(...)).
function tintHex(hex: string, alphaHex: string): string | undefined {
  return hex.startsWith('#') && hex.length === 7 ? `${hex}${alphaHex}` : undefined;
}

export function TreeBranch({
  label,
  color,
  badge,
  badgeColor,
  children,
}: {
  label: string;
  color?: string;
  badge?: string;
  badgeColor?: string;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const colorVars = color ? ({ '--branch-color': color } as CSSProperties) : undefined;
  const badgeTint = badgeColor ? tintHex(badgeColor, '1F') : undefined;

  return (
    <li>
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        aria-expanded={!collapsed}
        className="flex w-full items-center gap-2.5 rounded-lg border border-hairline px-3 py-2.5 text-xs uppercase tracking-widest text-muted hover:border-muted theme-light:border-transparent theme-light:shadow-neu-sm"
        style={color ? { ...colorVars, backgroundColor: tintHex(color, '12') ?? 'rgb(var(--color-surface))' } : undefined}
      >
        {color && (
          <span
            aria-hidden="true"
            className="h-3 w-3 shrink-0 rounded-md"
            style={{ ...colorVars, backgroundColor: 'var(--branch-color)' }}
          />
        )}
        <span className="text-ink">{label}</span>
        {badge && (
          <span
            className="ml-auto shrink-0 rounded-full px-2 py-0.5 text-[11px] normal-case tracking-normal"
            style={badgeColor ? { color: badgeColor, backgroundColor: badgeTint } : undefined}
          >
            {badge}
          </span>
        )}
        <span aria-hidden="true" className="text-[10px]">
          {collapsed ? '▸' : '▾'}
        </span>
      </button>
      {/* The connector line is the branch's own identity thread -- colored
          when the branch has a category color, so the line itself (not just
          a dot) reads as "everything boxed along this thread belongs to
          this branch," matching how the sector palette is used everywhere
          else in this feature. */}
      {!collapsed && (
        <ul
          className="ml-2 mt-1.5 flex flex-col gap-1.5 border-l-2 border-hairline pl-3"
          style={color ? { ...colorVars, borderColor: 'var(--branch-color)' } : undefined}
        >
          {children}
        </ul>
      )}
    </li>
  );
}

export function TreeLeaf({
  ticker,
  direction,
  badge,
  badgeColor,
  onClick,
}: {
  ticker: string;
  direction: string;
  badge?: string;
  badgeColor?: string;
  onClick: () => void;
}) {
  const bullish = direction === 'bullish';
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className={`flex w-full items-center gap-2 rounded-md border-y border-r border-hairline border-l-[3px] bg-surface px-3 py-2 text-left text-sm text-ink hover:border-muted theme-light:border-y-transparent theme-light:border-r-transparent theme-light:shadow-neu-sm ${
          bullish ? 'border-l-bullish' : 'border-l-bearish'
        }`}
      >
        <span aria-hidden="true" className={bullish ? 'text-bullish' : 'text-bearish'}>
          {bullish ? '▲' : '▼'}
        </span>
        {/* Monospace for the ticker only -- financial tape/ledger
            convention (fixed-width symbols), not applied to company names
            or labels elsewhere, so it reads as a deliberate nod to the
            subject matter rather than a global typographic shift. */}
        <span className="truncate font-mono text-[13px] tracking-tight">{ticker}</span>
        {badge && (
          <span
            className={`ml-auto shrink-0 text-xs ${badgeColor ? '' : 'text-muted'}`}
            style={badgeColor ? { color: badgeColor } : undefined}
          >
            {badge}
          </span>
        )}
      </button>
    </li>
  );
}
