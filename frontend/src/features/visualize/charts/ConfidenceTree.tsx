import { useLanguage } from '../../../lib/language';
import type { AlertCompany } from '../../../lib/api';
import { BAND_LABEL_KEY } from '../../../components/ConfidenceBandPill';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { rankByConfidence } from '../transforms';
import { confidenceBandColor, confidenceBandFromScore, confidenceColor } from '../colors';
import { TreeRoot, TreeBranch, TreeLeaf } from './tree/Tree';
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
  const { toggle, selected } = useCompanySelection(companies);

  if (companies.length === 0) return null;

  const groups = BAND_ORDER.map((band) => ({
    band,
    companies: rankByConfidence(companies.filter((c) => confidenceBandFromScore(c.confidence_score) === band)),
  })).filter((g) => g.companies.length > 0);

  return (
    <div className="flex flex-col gap-3 p-4">
      <TreeRoot>
        {groups.map((group) => (
          <TreeBranch
            key={group.band}
            label={t(BAND_LABEL_KEY[group.band])}
            color={confidenceBandColor(group.band)}
            badge={`${group.companies.length}`}
            badgeColor={confidenceBandColor(group.band)}
          >
            {group.companies.map((c) => (
              <TreeLeaf
                key={c.company_id}
                ticker={c.ticker}
                direction={c.direction}
                badge={`${c.confidence_score}%`}
                badgeColor={confidenceColor(c.confidence_score)}
                onClick={() => toggle(c.company_id)}
              />
            ))}
          </TreeBranch>
        ))}
      </TreeRoot>
      {selected && <ReasoningPanel company={selected} eventType={eventType} />}
    </div>
  );
}
