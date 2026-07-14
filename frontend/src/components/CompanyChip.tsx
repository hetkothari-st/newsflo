import { useState, type KeyboardEvent } from 'react';
import type { AlertCompany } from '../lib/api';
import CompanyAvatar from './CompanyAvatar';
import DirectionArrow from './DirectionArrow';
import ReasoningPanel from './ReasoningPanel';

export default function CompanyChip({ company }: { company: AlertCompany }) {
  const [expanded, setExpanded] = useState(false);

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
            <DirectionArrow direction={company.direction} />
            <span className="truncate">{company.name}</span>
          </span>
          <span className="truncate text-[11px] uppercase tracking-wide text-muted">{company.ticker}</span>
        </div>
      </div>
      {expanded && <ReasoningPanel company={company} />}
    </div>
  );
}
