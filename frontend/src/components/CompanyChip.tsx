import { useState, type KeyboardEvent } from 'react';
import type { AlertCompany } from '../lib/api';
import ReasoningPanel from './ReasoningPanel';

// No verified per-company domain/logo exists in the data model — guessing a
// domain from the ticker risks rendering a different company's real brand
// mark (e.g. "reliance.com" belongs to a US steel company, not Reliance
// Industries). A deterministic monogram is the honest stand-in: same ticker
// always resolves to the same initials + color, no network fetch, no risk of
// a wrong logo. Swap in a real <img src={logo_url}> here if the backend ever
// adds a verified logo field.
const AVATAR_PALETTE = [
  '#F5A623', // amber
  '#4A90D9', // blue
  '#2DD4BF', // teal
  '#E85D4C', // red-orange
  '#9B7EDE', // violet
  '#5FB878', // green
  '#D4708C', // rose
  '#6C8CD5', // indigo
];

function avatarColor(ticker: string): string {
  let hash = 0;
  for (let i = 0; i < ticker.length; i++) hash = (hash * 31 + ticker.charCodeAt(i)) >>> 0;
  return AVATAR_PALETTE[hash % AVATAR_PALETTE.length];
}

function initials(ticker: string): string {
  const base = ticker.split('.')[0];
  return base.slice(0, 2).toUpperCase();
}

function CompanyAvatar({ ticker }: { ticker: string }) {
  return (
    <span
      aria-hidden="true"
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-xs font-bold text-page"
      style={{ backgroundColor: avatarColor(ticker) }}
    >
      {initials(ticker)}
    </span>
  );
}

export default function CompanyChip({ company }: { company: AlertCompany }) {
  const [expanded, setExpanded] = useState(false);
  const bullish = company.direction === 'bullish';
  const directionClass = bullish ? 'text-bullish' : 'text-bearish';

  function toggle() {
    setExpanded((v) => !v);
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggle();
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={toggle}
        onKeyDown={onKeyDown}
        className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-hairline bg-page p-3 motion-safe:transition-colors hover:border-muted theme-light:shadow-neu-sm"
      >
        <CompanyAvatar ticker={company.ticker} />
        <div className="flex min-w-0 flex-col">
          <span className="flex items-center gap-1.5 truncate text-sm text-ink">
            <span aria-hidden="true" className={directionClass}>
              {bullish ? '▲' : '▼'}
            </span>
            <span className="truncate">{company.name}</span>
          </span>
          <span className="truncate text-[11px] uppercase tracking-wide text-muted">{company.ticker}</span>
        </div>
      </div>
      {expanded && <ReasoningPanel company={company} />}
    </div>
  );
}
