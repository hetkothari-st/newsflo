import { useState, type CSSProperties, type ReactNode } from 'react';

export function TreeRoot({ children }: { children: ReactNode }) {
  return <ul className="flex flex-col gap-1">{children}</ul>;
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

  return (
    <li className="border-l-2 border-hairline pl-3">
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        aria-expanded={!collapsed}
        className="flex items-center gap-1.5 py-1 text-xs uppercase tracking-widest text-muted"
      >
        {color && (
          <span
            aria-hidden="true"
            className="h-2 w-2 rounded-full"
            style={{ '--dot-color': color, backgroundColor: 'var(--dot-color)' } as CSSProperties}
          />
        )}
        <span>{label}</span>
        <span aria-hidden="true" className="text-[10px]">
          {collapsed ? '▸' : '▾'}
        </span>
      </button>
      {!collapsed && <ul className="flex flex-col gap-0.5 border-l border-hairline pl-3">{children}</ul>}
    </li>
  );
}

export function TreeLeaf({
  ticker,
  direction,
  badge,
  onClick,
}: {
  ticker: string;
  direction: string;
  badge?: string;
  onClick: () => void;
}) {
  const bullish = direction === 'bullish';
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className="flex w-full items-center gap-2 border-b border-hairline/50 py-1.5 text-left text-sm text-ink last:border-b-0"
      >
        <span aria-hidden="true" className={bullish ? 'text-bullish' : 'text-bearish'}>
          {bullish ? '▲' : '▼'}
        </span>
        <span className="truncate">{ticker}</span>
        {badge && <span className="ml-auto shrink-0 text-xs text-muted">{badge}</span>}
      </button>
    </li>
  );
}
