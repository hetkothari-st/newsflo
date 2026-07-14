import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { rankByMagnitude } from '../transforms';
import { TreeRoot, TreeBranch, TreeLeaf } from './tree/Tree';
import { useCompanySelection } from './useCompanySelection';

export default function SplitTree({ companies }: { companies: AlertCompany[] }) {
  const { toggle, selected } = useCompanySelection(companies);
  const bullish = rankByMagnitude(companies.filter((c) => c.direction === 'bullish'));
  const bearish = rankByMagnitude(companies.filter((c) => c.direction === 'bearish'));

  if (bullish.length === 0 && bearish.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      <p className="text-xs">
        <span className="text-bullish">{bullish.length} Bullish</span>
        <span className="text-muted"> · </span>
        <span className="text-bearish">{bearish.length} Bearish</span>
      </p>
      <TreeRoot>
        {bullish.length > 0 && (
          <TreeBranch label="Bullish">
            {bullish.map((c) => (
              <TreeLeaf key={c.company_id} ticker={c.ticker} direction={c.direction} onClick={() => toggle(c.company_id)} />
            ))}
          </TreeBranch>
        )}
        {bearish.length > 0 && (
          <TreeBranch label="Bearish">
            {bearish.map((c) => (
              <TreeLeaf key={c.company_id} ticker={c.ticker} direction={c.direction} onClick={() => toggle(c.company_id)} />
            ))}
          </TreeBranch>
        )}
      </TreeRoot>
      {selected && <ReasoningPanel company={selected} />}
    </div>
  );
}
