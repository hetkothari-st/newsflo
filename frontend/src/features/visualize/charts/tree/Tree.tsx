import { useState, type CSSProperties, type ReactNode } from 'react';

export function TreeRoot({ children }: { children: ReactNode }) {
  return <ul className="flex flex-col gap-3">{children}</ul>;
}

export function TreeBranch({
  label,
  color,
  children,
}: {
  label: string;
  color?: string;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const colorVars = color ? ({ '--branch-color': color } as CSSProperties) : undefined;

  return (
    <li>
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        aria-expanded={!collapsed}
        className="flex items-center gap-2 py-1 text-xs uppercase tracking-widest text-muted"
      >
        {color && (
          <span
            aria-hidden="true"
            className="h-2 w-2 rounded-full"
            style={{ ...colorVars, backgroundColor: 'var(--branch-color)' }}
          />
        )}
        <span>{label}</span>
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
          className="ml-1 flex flex-col gap-1.5 border-l-2 border-hairline pl-3"
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
        className="flex w-full items-center gap-2 rounded-md border border-hairline bg-surface px-3 py-2 text-left text-sm text-ink hover:border-muted theme-light:border-transparent theme-light:shadow-neu-sm"
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
