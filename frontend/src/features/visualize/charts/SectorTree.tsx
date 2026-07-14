import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { groupBySector } from '../transforms';
import { TreeRoot, TreeBranch, TreeLeaf } from './tree/Tree';
import { useCompanySelection } from './useCompanySelection';

export default function SectorTree({ companies }: { companies: AlertCompany[] }) {
  const { toggle, selected } = useCompanySelection(companies);
  const groups = groupBySector(companies);

  if (groups.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      <TreeRoot>
        {groups.map((group) => (
          <TreeBranch key={group.key} label={group.label} color={group.color}>
            {group.companies.map((c) => (
              <TreeLeaf key={c.company_id} ticker={c.ticker} direction={c.direction} onClick={() => toggle(c.company_id)} />
            ))}
          </TreeBranch>
        ))}
      </TreeRoot>
      {selected && <ReasoningPanel company={selected} />}
    </div>
  );
}
