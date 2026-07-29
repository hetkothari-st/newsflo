import { useState } from 'react';
import type { AlertCompany } from '../lib/api';
import CompanyLogo from './CompanyLogo';
import InsightCard from './InsightCard';

// Collapsed by default so a 16-company alert doesn't dump 16 full insight
// cards on the user at once. ONE persistent header row (logo, name, ticker,
// direction) is the single toggle -- clicking it either way (open or close)
// hits the exact same row, at the exact same spot, every time. Earlier this
// swapped in a completely different all-caps "name" line while expanded,
// duplicating InsightCard's own header right below it and leaving no
// obvious way back to collapsed -- InsightCard's hideHeader prop now
// suppresses that inner duplicate instead. Uncontrolled per-row state --
// each row remembers its own expanded/collapsed state independent of its
// siblings.
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

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-3 rounded-sm border-b border-hairline py-2.5 text-left outline-none transition-colors hover:bg-elevated/60 focus-visible:ring-1 focus-visible:ring-hairline"
      >
        <span
          aria-hidden="true"
          className="font-data text-[11px] text-muted transition-transform duration-150"
          style={{ transform: expanded ? 'rotate(90deg)' : 'none' }}
        >
          ▸
        </span>
        <CompanyLogo logoUrl={company.logo_url} ticker={company.ticker} sector={company.sector} size="sm" />
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
      {expanded && (
        <InsightCard
          company={company}
          eventType={eventType}
          alertCreatedAt={alertCreatedAt}
          alertId={alertId}
          parentCompany={parentCompany}
          hideHeader
        />
      )}
    </div>
  );
}
