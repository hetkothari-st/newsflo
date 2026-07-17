import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { AlertCompany, PricePoint } from '../lib/api';
import { getCompanyPrices } from '../lib/api';
import { useLanguage } from '../lib/language';
import { eventTypeLabel } from '../lib/ruleLabels';
import { formatRelativeTime } from '../lib/relativeTime';
import { sectorLabel } from '../features/visualize/transforms';
import CompanyLogo from './CompanyLogo';
import InsightSparkline from './InsightSparkline';
import InsightGauges from './InsightGauges';

function truncatedRationale(rationale: string): string {
  const firstSentence = rationale.split(/(?<=[.!?])\s+/)[0];
  if (firstSentence.length <= 160) return firstSentence;
  return `${firstSentence.slice(0, 157)}…`;
}

export default function InsightCard({
  company,
  eventType,
  alertCreatedAt,
  alertId,
}: {
  company: AlertCompany;
  eventType?: string | null;
  alertCreatedAt: string;
  alertId?: number;
}) {
  const { language, t } = useLanguage();
  const [expanded, setExpanded] = useState(false);
  const [points, setPoints] = useState<PricePoint[]>([]);

  useEffect(() => {
    let cancelled = false;
    getCompanyPrices(company.company_id, '1mo')
      .then((series) => {
        if (!cancelled && series.available) setPoints(series.points);
      })
      .catch(() => {
        // Sparkline is decorative context, not critical data -- degrade to
        // no chart rather than surfacing a fetch error in the feed.
      });
    return () => {
      cancelled = true;
    };
  }, [company.company_id]);

  const points_ = company.key_points.length > 0 ? company.key_points : [truncatedRationale(company.rationale)];
  const summary = points_[0];
  const extraPoints = points_.slice(1);

  const priceLine =
    company.price_at_analysis != null ? (
      <span className={company.direction === 'bearish' ? 'text-bearish' : 'text-bullish'}>
        <span aria-hidden="true">{company.direction === 'bearish' ? '▼' : '▲'}</span>{' '}
        <span className="font-data">
          {company.market === 'IN' ? '₹' : '$'}
          {company.price_at_analysis.toFixed(2)}
        </span>
        {company.return_1m != null && (
          <span className="font-data block text-right text-xs">
            {company.return_1m >= 0 ? '+' : ''}
            {company.return_1m.toFixed(1)}%
          </span>
        )}
      </span>
    ) : null;

  return (
    <div className="border-b border-hairline py-4 font-editorial">
      <div className="flex items-baseline justify-between font-data text-[11px] uppercase tracking-widest text-muted">
        <span>
          {eventType ? eventTypeLabel(eventType) : ''}
          {eventType && company.sector ? ' · ' : ''}
          {company.sector ? sectorLabel(company.sector) : ''}
        </span>
        <span>{formatRelativeTime(alertCreatedAt, new Date(), language)}</span>
      </div>

      <div className="mt-3 flex items-center gap-3.5">
        <CompanyLogo logoUrl={company.logo_url} ticker={company.ticker} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[22px] font-semibold leading-tight text-ink">{company.name}</p>
          <p className="font-data text-xs text-muted">{company.ticker}</p>
        </div>
        {priceLine && <div className="shrink-0 text-right text-base">{priceLine}</div>}
      </div>

      {points.length >= 2 && (
        <div className="mt-3">
          <InsightSparkline points={points} direction={company.direction} />
        </div>
      )}

      <InsightGauges
        confidenceScore={company.confidence_score}
        timeHorizon={company.time_horizon}
        impactLevel={company.impact_level}
      />

      <p className="mt-3 text-base leading-relaxed text-ink">{summary}</p>

      {expanded && extraPoints.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1.5 text-sm text-ink">
          {extraPoints.map((point, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-muted" aria-hidden="true">
                •
              </span>
              <span>{point}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex items-center justify-between font-data text-[11.5px]">
        {extraPoints.length > 0 ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-muted"
          >
            {expanded ? t('insights.seeLess') : t('insights.seeMoreInsights', { n: extraPoints.length })}
          </button>
        ) : (
          <span />
        )}
        {alertId != null && (
          <Link
            to={`/alerts/${alertId}/company/${company.company_id}`}
            className="uppercase tracking-widest text-ink underline"
          >
            {t('insights.readFullAnalysis')} →
          </Link>
        )}
      </div>
    </div>
  );
}
