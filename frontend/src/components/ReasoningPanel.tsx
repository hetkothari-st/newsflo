import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { AlertCompany } from '../lib/api';
import { precedentLine, splitRationaleIntoPoints } from '../lib/reasoning';
import { useLanguage } from '../lib/language';
import { eventTypeLabel, formatEvidenceRef } from '../lib/ruleLabels';
import ConfidenceBandPill from './ConfidenceBandPill';
import MentionRow from './MentionRow';

// Re-exported so this stays the one import path components/tests already use.
export { precedentLine, splitRationaleIntoPoints };

export default function ReasoningPanel({
  company,
  eventType,
}: {
  company: AlertCompany;
  eventType?: string | null;
}) {
  const { language, t } = useLanguage();
  const [whyOpen, setWhyOpen] = useState(false);
  // key_points is the model's own short, terse summary -- prefer it. Fall
  // back to sentence-splitting the full rationale only for alerts analyzed
  // before key_points existed (empty array).
  const points = company.key_points.length > 0 ? company.key_points : splitRationaleIntoPoints(company.rationale);
  const reasons = company.reasons ?? [];
  const evidenceRefs = company.evidence_refs ?? [];
  const caveats = [...(company.risks ?? []), ...(company.assumptions ?? []), ...(company.unknowns ?? [])];
  const contributors = company.confidence_contributors ?? [];
  const penalties = company.confidence_penalties ?? [];
  const hasEvidenceSection = reasons.length > 0;

  return (
    <div className="rounded-lg border border-hairline bg-surface px-3 py-3">
      <p className="flex items-center text-xs uppercase tracking-widest text-muted">
        {company.name} · {company.ticker}
        <ConfidenceBandPill band={company.confidence_band} />
      </p>
      <ul className="mt-2 space-y-1.5 text-sm text-ink">
        {points.map((point, i) => (
          <li key={i} className="flex gap-2">
            <span className="text-muted" aria-hidden="true">•</span>
            <span>{point}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">{precedentLine(company, language)}</p>
      {hasEvidenceSection && (
        <div className="mt-3 border-t border-hairline pt-2">
          <button
            type="button"
            onClick={() => setWhyOpen((v) => !v)}
            aria-expanded={whyOpen}
            className="flex items-center gap-1 text-xs uppercase tracking-widest text-ink"
          >
            <span aria-hidden="true">{whyOpen ? '▾' : '▸'}</span>
            {t('reasoning.whyThisCall')}
          </button>
          {whyOpen && (
            <div className="mt-2 flex flex-col gap-2.5 text-xs">
              <div>
                <p className="uppercase tracking-widest text-muted">{t('reasoning.reasoningHeading')}</p>
                <ul className="mt-1 space-y-1 text-ink">
                  {reasons.map((reason, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="text-muted" aria-hidden="true">•</span>
                      <span>{reason}</span>
                    </li>
                  ))}
                </ul>
              </div>
              {evidenceRefs.length > 0 && (
                <div>
                  <p className="uppercase tracking-widest text-muted">{t('reasoning.evidenceHeading')}</p>
                  <ul className="mt-1 space-y-1 text-ink">
                    {evidenceRefs.map((ref, i) => {
                      const { text, kind } = formatEvidenceRef(ref);
                      if (kind === 'rule') {
                        return (
                          <li key={i}>
                            <span className="inline-flex items-center rounded-full bg-hairline px-1.5 py-0.5 text-[10px] text-muted">
                              {text}
                            </span>
                          </li>
                        );
                      }
                      if (kind === 'article' || kind === 'historical') {
                        const label =
                          kind === 'article' ? t('reasoning.evidenceArticle') : t('reasoning.evidenceHistorical');
                        return (
                          <li key={i}>
                            <sup className="mr-1 text-[9px] uppercase tracking-widest text-muted">{label}</sup>
                            {text}
                          </li>
                        );
                      }
                      return <li key={i}>{text}</li>;
                    })}
                  </ul>
                </div>
              )}
              {company.alternative_hypothesis && (
                <div>
                  <p className="uppercase tracking-widest text-muted">{t('reasoning.alternativeView')}</p>
                  <p className="mt-1 italic text-ink">{company.alternative_hypothesis}</p>
                </div>
              )}
              {caveats.length > 0 && (
                <div>
                  <p className="uppercase tracking-widest text-muted">{t('reasoning.risksAndUnknowns')}</p>
                  <ul className="mt-1 space-y-1 text-ink">
                    {caveats.map((c, i) => (
                      <li key={i} className="flex gap-2">
                        <span className="text-muted" aria-hidden="true">•</span>
                        <span>{c}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {(contributors.length > 0 || penalties.length > 0) && (
                <div>
                  <p className="uppercase tracking-widest text-muted">{t('reasoning.confidenceBreakdown')}</p>
                  <ul className="mt-1 space-y-1">
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
                </div>
              )}
              {eventType && (
                <p className="text-muted">
                  {t('reasoning.eventType', { type: eventTypeLabel(eventType) })}
                </p>
              )}
            </div>
          )}
        </div>
      )}
      {company.past_mentions.length > 0 && (
        <div className="mt-3 border-t border-hairline pt-2">
          <p className="text-xs uppercase tracking-widest text-muted">{t('reasoning.previously')}</p>
          <ul className="mt-1.5 space-y-1">
            {company.past_mentions.map((mention) => (
              <MentionRow key={mention.alert_id} mention={mention} />
            ))}
          </ul>
        </div>
      )}
      {company.market === 'IN' && (
        <Link
          to={`/company/${company.company_id}`}
          className="mt-3 inline-block text-xs uppercase tracking-widest text-ink underline"
        >
          {t('reasoning.viewDetails')}
        </Link>
      )}
    </div>
  );
}
