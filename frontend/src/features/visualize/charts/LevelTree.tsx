import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { computeNetSignal, type NetSignal } from '../transforms';
import { IMPACT_LEVEL_ORDER, impactLevelColor, impactLevelKey, impactLevelLabel } from '../impactLevels';
import { TreeRoot, TreeBranch, TreeLeaf } from './tree/Tree';
import { useCompanySelection } from './useCompanySelection';

function signalBadge(signal: NetSignal): { text: string; color?: string } {
  if (signal.direction === 'even') return { text: `▬ ${signal.avgConfidence}%` };
  const bullish = signal.direction === 'bullish';
  return {
    text: `${bullish ? '▲' : '▼'} ${signal.avgConfidence}%`,
    color: bullish ? 'rgb(var(--color-bullish))' : 'rgb(var(--color-bearish))',
  };
}

// Groups indirect companies at one level by the parent company (from the
// PREVIOUS level) they're economically linked through -- e.g. every
// indirect_l1 entry naming the same direct company as its parent_company_id
// becomes one branch labeled with that direct company's own name/ticker.
function groupByParent(levelCompanies: AlertCompany[], allCompanies: AlertCompany[]) {
  const byId = new Map(allCompanies.map((c) => [c.company_id, c]));
  const byParent = new Map<number, AlertCompany[]>();
  const orphaned: AlertCompany[] = [];
  for (const c of levelCompanies) {
    if (c.parent_company_id == null) {
      orphaned.push(c);
      continue;
    }
    const group = byParent.get(c.parent_company_id) ?? [];
    group.push(c);
    byParent.set(c.parent_company_id, group);
  }
  const groups = [...byParent.entries()].map(([parentId, kids]) => {
    const parent = byId.get(parentId);
    return {
      key: `parent-${parentId}`,
      label: parent ? `via ${parent.name} (${parent.ticker})` : `via company #${parentId}`,
      companies: kids,
    };
  });
  return { groups, orphaned };
}

export default function LevelTree({
  companies,
  eventType,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected } = useCompanySelection(companies);

  const levels = IMPACT_LEVEL_ORDER.map((level) => ({
    level,
    companies: companies.filter((c) => impactLevelKey(c) === level),
  })).filter((l) => l.companies.length > 0);

  if (levels.length === 0) return null;

  return (
    <div className="flex flex-col gap-4 p-4">
      <TreeRoot>
        {levels.map(({ level, companies: levelCompanies }) => {
          const badge = signalBadge(computeNetSignal(levelCompanies));
          const color = impactLevelColor(level);
          if (level === 'direct') {
            return (
              <TreeBranch key={level} label={impactLevelLabel(level)} color={color} badge={badge.text} badgeColor={badge.color}>
                {levelCompanies.map((c) => (
                  <TreeLeaf key={c.company_id} ticker={c.ticker} direction={c.direction} onClick={() => toggle(c.company_id)} />
                ))}
              </TreeBranch>
            );
          }
          const { groups, orphaned } = groupByParent(levelCompanies, companies);
          return (
            <TreeBranch key={level} label={impactLevelLabel(level)} color={color} badge={badge.text} badgeColor={badge.color}>
              {groups.map((group) => (
                <TreeBranch key={group.key} label={group.label} color={color}>
                  {group.companies.map((c) => (
                    <TreeLeaf key={c.company_id} ticker={c.ticker} direction={c.direction} onClick={() => toggle(c.company_id)} />
                  ))}
                </TreeBranch>
              ))}
              {orphaned.map((c) => (
                <TreeLeaf key={c.company_id} ticker={c.ticker} direction={c.direction} onClick={() => toggle(c.company_id)} />
              ))}
            </TreeBranch>
          );
        })}
      </TreeRoot>
      {selected && <ReasoningPanel company={selected} eventType={eventType} />}
    </div>
  );
}
