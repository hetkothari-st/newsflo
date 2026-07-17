import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import type { Alert, AlertCompany, PricePoint } from '../lib/api';
import { getAlert, getCompanyPrices } from '../lib/api';
import { useLanguage } from '../lib/language';
import { eventTypeLabel, formatEvidenceRef } from '../lib/ruleLabels';
import CompanyLogo from '../components/CompanyLogo';
import InsightSparkline from '../components/InsightSparkline';
import InsightGauges from '../components/InsightGauges';
import MentionRow from '../components/MentionRow';

export default function AlertCompanyAnalysisPage() {
  const { id, companyId } = useParams<{ id: string; companyId: string }>();
  const { t } = useLanguage();
  const [alert, setAlert] = useState<Alert | null>(null);
  const [loading, setLoading] = useState(true);
  const [points, setPoints] = useState<PricePoint[]>([]);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    getAlert(Number(id))
      .then(setAlert)
      .finally(() => setLoading(false));
  }, [id]);

  const company: AlertCompany | undefined = alert?.companies.find(
    (c) => c.company_id === Number(companyId),
  );

  useEffect(() => {
    if (!company) return;
    let cancelled = false;
    getCompanyPrices(company.company_id, '3mo')
      .then((series) => {
        if (!cancelled && series.available) setPoints(series.points);
      })
      .catch(() => {
        // Sparkline is decorative context, not critical data -- degrade to
        // no chart rather than surfacing a fetch error on this page.
      });
    return () => {
      cancelled = true;
    };
  }, [company]);

  if (loading) return null;

  if (!alert || !company) {
    return <p className="mx-auto max-w-feed px-4 py-8 text-sm text-muted">Company not found in this alert.</p>;
  }

  const evidenceRefs = company.evidence_refs ?? [];
  const reasons = company.reasons ?? [];
  const risks = company.risks ?? [];
  const assumptions = company.assumptions ?? [];
  const unknowns = company.unknowns ?? [];
  const contributors = company.confidence_contributors ?? [];
  const penalties = company.confidence_penalties ?? [];

  return (
    <div className="mx-auto max-w-feed px-4 py-8 font-editorial">
      <p className="font-data text-[11px] uppercase tracking-widest text-muted">
        {alert.event_type ? eventTypeLabel(alert.event_type) : ''}
        {alert.event_type && company.sector ? ' · ' : ''}
        {company.sector ?? ''}
      </p>

      <div className="mt-3 flex items-center gap-4">
        <CompanyLogo logoUrl={company.logo_url} ticker={company.ticker} size="lg" />
        <div>
          <p className="text-[28px] font-semibold leading-tight text-ink">{company.name}</p>
          <p className="font-data text-xs text-muted">{company.ticker}</p>
        </div>
      </div>

      {points.length >= 2 && (
        <div className="mt-4">
          <InsightSparkline points={points} direction={company.direction} />
        </div>
      )}

      <InsightGauges
        confidenceScore={company.confidence_score}
        timeHorizon={company.time_horizon}
        impactLevel={company.impact_level}
      />

      <div className="mt-4 border-t border-hairline pt-3">
        <p className="font-data text-[10.5px] uppercase tracking-widest text-muted">Confidence</p>
        <div className="mt-1.5 h-0.5 w-full bg-hairline">
          <div className="h-full bg-bullish" style={{ width: `${company.confidence_score}%` }} />
        </div>
        {(contributors.length > 0 || penalties.length > 0) && (
          <ul className="mt-2 flex flex-col gap-1 font-data text-xs">
            {contributors.map((c, i) => (
              <li key={`c-${i}`} className="flex gap-2 text-bullish">
                <span aria-hidden="true">+</span>
                <span>{c}</span>
              </li>
            ))}
            {penalties.map((p, i) => (
              <li key={`p-${i}`} className="flex gap-2 text-bearish">
                <span aria-hidden="true">−</span>
                <span>{p}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {reasons.length > 0 && (
        <div className="mt-4 border-t border-hairline pt-3">
          <p className="font-data text-[10.5px] uppercase tracking-widest text-muted">Reasons &amp; evidence</p>
          <ol className="mt-2 flex flex-col gap-2 text-sm text-ink">
            {reasons.map((reason, i) => (
              <li key={i} className="flex gap-2">
                <span className="font-data text-muted">{i + 1}.</span>
                <div>
                  <p>{reason}</p>
                  {evidenceRefs[i] && (
                    <p className="font-data text-xs text-muted">{formatEvidenceRef(evidenceRefs[i]).text}</p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}

      {company.alternative_hypothesis && (
        <div className="mt-4 border-l-2 border-hairline pl-3.5 italic text-muted">
          <p className="mb-1 font-data text-[10.5px] uppercase not-italic tracking-widest text-muted">
            Alternative read
          </p>
          {company.alternative_hypothesis}
        </div>
      )}

      {(risks.length > 0 || assumptions.length > 0 || unknowns.length > 0) && (
        <div className="mt-4 border-t border-hairline pt-3">
          <p className="font-data text-[10.5px] uppercase tracking-widest text-muted">Risks, assumptions &amp; unknowns</p>
          <ul className="mt-2 flex flex-col gap-1 text-sm text-ink">
            {[...risks, ...assumptions, ...unknowns].map((item, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-muted" aria-hidden="true">•</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {company.price_at_analysis != null && (
        <div className="mt-4 border-t border-hairline pt-3">
          <p className="font-data text-[10.5px] uppercase tracking-widest text-muted">{t('reasoning.factsHeading')}</p>
          <div className="mt-1.5 font-data text-sm text-ink">
            <span>
              {company.market === 'IN' ? '₹' : '$'}
              {company.price_at_analysis.toFixed(2)}
            </span>
            {company.return_1m != null && (
              <span className={`ml-3 ${company.return_1m >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                {company.return_1m >= 0 ? '+' : ''}
                {company.return_1m.toFixed(1)}% (1M)
              </span>
            )}
            {company.return_3m != null && (
              <span className={`ml-3 ${company.return_3m >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                {company.return_3m >= 0 ? '+' : ''}
                {company.return_3m.toFixed(1)}% (3M)
              </span>
            )}
          </div>
          {company.contradiction_note && (
            <p className="mt-2 flex items-start gap-1.5 text-bearish">
              <span aria-hidden="true">⚠</span>
              <span>{company.contradiction_note}</span>
            </p>
          )}
        </div>
      )}

      {company.past_mentions.length > 0 && (
        <div className="mt-4 border-t border-hairline pt-3">
          <p className="font-data text-[10.5px] uppercase tracking-widest text-muted">{t('reasoning.previously')}</p>
          <ul className="mt-1.5 flex flex-col gap-1">
            {company.past_mentions.map((mention) => (
              <MentionRow key={mention.alert_id} mention={mention} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
