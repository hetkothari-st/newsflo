import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { rankByConfidence } from '../transforms';
import { confidenceColor } from '../colors';
import { TreeRoot, TreeLeaf } from './tree/Tree';
import { useCompanySelection } from './useCompanySelection';

export default function ConfidenceTree({
  companies,
  eventType,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected } = useCompanySelection(companies);
  const ranked = rankByConfidence(companies);

  if (ranked.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      <TreeRoot>
        {ranked.map((c) => (
          <TreeLeaf
            key={c.company_id}
            ticker={c.ticker}
            direction={c.direction}
            badge={`${c.confidence_score}%`}
            badgeColor={confidenceColor(c.confidence_score)}
            onClick={() => toggle(c.company_id)}
          />
        ))}
      </TreeRoot>
      {selected && <ReasoningPanel company={selected} eventType={eventType} />}
    </div>
  );
}
