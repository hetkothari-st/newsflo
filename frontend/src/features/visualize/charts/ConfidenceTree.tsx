import { useLanguage } from '../../../lib/language';
import type { AlertCompany } from '../../../lib/api';
import { BAND_LABEL_KEY } from '../../../components/ConfidenceBandPill';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { computeNetSignal, rankByConfidence } from '../transforms';
import { confidenceBandColor, confidenceBandFromScore } from '../colors';
import ChartCardShell from './ChartCardShell';
import ImpactCard from './cards/ImpactCard';
import CompanyRow from './cards/CompanyRow';
import { useCompanySelection } from './useCompanySelection';

// Highest-confidence band first -- matches the mockup's Confidence Tree,
// which reads top-to-bottom as High -> Medium -> Low Confidence.
const BAND_ORDER = ['VERY_HIGH', 'HIGH', 'MODERATE', 'LOW'] as const;

export default function ConfidenceTree({
  companies,
  eventType,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { t } = useLanguage();
  const { toggle, selected, selectedId } = useCompanySelection(companies);

  if (companies.length === 0) return null;

  const groups = BAND_ORDER.map((band) => ({
    band,
    companies: rankByConfidence(companies.filter((c) => confidenceBandFromScore(c.confidence_score) === band)),
  })).filter((g) => g.companies.length > 0);

  return (
    <ChartCardShell
      number={5}
      title="Confidence Tree"
      description="Tree showing companies with confidence scores for impact"
      legend={groups.map((g) => ({ label: t(BAND_LABEL_KEY[g.band]), color: confidenceBandColor(g.band) }))}
    >
      <div className="flex flex-col gap-4 p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {groups.map((group) => (
            <ImpactCard
              key={group.band}
              label={t(BAND_LABEL_KEY[group.band])}
              color={confidenceBandColor(group.band)}
              signal={computeNetSignal(group.companies)}
              companyCount={group.companies.length}
            >
              {group.companies.map((c) => (
                <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => toggle(c.company_id)} />
              ))}
            </ImpactCard>
          ))}
        </div>
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
