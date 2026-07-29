import { useState } from 'react';
import type { AlertCompany } from '../lib/api';
import CompanyLogo from './CompanyLogo';
import InsightCard from './InsightCard';

// Collapsed by default so a 16-company alert doesn't dump 16 full insight
// cards on the user at once -- shows just enough to pick which companies
// are worth reading (name, ticker, direction) and expands to the full
// InsightCard (insights, sector-membership line, sparkline, etc.) only on
// click. Uncontrolled per-row state -- each row remembers its own
// expanded/collapsed state independent of its siblings.
export default function CollapsibleInsightRow({
  company,
  eventType,
  alertCreatedAt,
  alertId,
  parentCompany,
}: {
  company: AlertCompany;
  eventType?: string | null;
  alertCreatedAt: string;
  alertId?: number;
  // See InsightCard's own parentCompany doc -- forwarded through unchanged.
  parentCompany?: AlertCompany | null;
}) {
  const [expanded, setExpanded] = useState(false);

  if (expanded) {
    return (
      <div>
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="flex w-full items-center gap-2 py-1 text-left font-data text-[11px] uppercase tracking-widest text-muted"
        >
          <span aria-hidden="true">▾</span>
          {company.name}
        </button>
        <InsightCard
          company={company}
          eventType={eventType}
          alertCreatedAt={alertCreatedAt}
          alertId={alertId}
          parentCompany={parentCompany}
        />
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setExpanded(true)}
      className="flex w-full items-center gap-3 border-b border-hairline py-2.5 text-left"
    >
      <span aria-hidden="true" className="font-data text-[11px] text-muted">▸</span>
      <CompanyLogo logoUrl={company.logo_url} ticker={company.ticker} size="sm" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold text-ink">{company.name}</span>
        <span className="font-data text-xs text-muted">
          {company.ticker}
          {/* Visible even before expanding -- the direct answer to "why is
              this company in the Ripple bucket" shouldn't require a click. */}
          {parentCompany && ` · via ${parentCompany.ticker}`}
        </span>
      </span>
      <span
        aria-hidden="true"
        className={`font-data text-xs ${company.direction === 'bearish' ? 'text-bearish' : 'text-bullish'}`}
      >
        {company.direction === 'bearish' ? '▼' : '▲'}
      </span>
    </button>
  );
}
