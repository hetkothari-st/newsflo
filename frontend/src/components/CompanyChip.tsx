import { useState, type KeyboardEvent } from 'react';
import type { AlertCompany } from '../lib/api';
import ReasoningPanel from './ReasoningPanel';

function fmtPct(v: number): string {
  return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;
}

export default function CompanyChip({ company }: { company: AlertCompany }) {
  const [expanded, setExpanded] = useState(false);
  const magnitudeClass = company.direction === 'bullish' ? 'text-bullish' : 'text-bearish';

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
        className="flex cursor-pointer items-center justify-between rounded-lg border border-hairline bg-surface px-3 py-2 motion-safe:transition-colors hover:border-muted"
      >
        <span className="text-sm text-ink">{company.name}</span>
        <span className={`text-xs tabular-nums ${magnitudeClass}`}>
          {fmtPct(company.magnitude_low)} to {fmtPct(company.magnitude_high)}
        </span>
      </div>
      {expanded && <ReasoningPanel company={company} />}
    </div>
  );
}
