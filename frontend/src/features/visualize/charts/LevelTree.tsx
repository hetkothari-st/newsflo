import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { computeNetSignal, groupBySector } from '../transforms';
import { sectorColor } from '../colors';
import { IMPACT_LEVEL_ORDER, impactLevelColor, impactLevelKey, impactLevelLabel } from '../impactLevels';
import ImpactCard from './cards/ImpactCard';
import CompanyRow from './cards/CompanyRow';
import { useCompanySelection } from './useCompanySelection';

// Groups indirect companies at one level by the parent company (from the
// level above) they're economically linked through -- e.g. every
// indirect_l1 entry naming the same direct company as parent_company_id
// becomes one card labeled with that direct company's own name/ticker.
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
      label: parent ? `Via ${parent.name} (${parent.ticker})` : `Via company #${parentId}`,
      companies: kids,
    };
  });
  return { groups, orphaned };
}

function LevelConnector() {
  return (
    <div aria-hidden="true" className="flex justify-center py-0.5">
      <span className="text-muted">↓</span>
    </div>
  );
}

export default function LevelTree({
  companies,
  eventType,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);

  const levels = IMPACT_LEVEL_ORDER.map((level) => ({
    level,
    companies: companies.filter((c) => impactLevelKey(c) === level),
  })).filter((l) => l.companies.length > 0);

  if (levels.length === 0) return null;

  return (
    <div className="flex flex-col p-4">
      {levels.map(({ level, companies: levelCompanies }, i) => {
        const color = impactLevelColor(level);
        const cards =
          level === 'direct'
            ? groupBySector(levelCompanies).map((g) => ({ key: g.key, label: g.label, companies: g.companies }))
            : (() => {
                const { groups, orphaned } = groupByParent(levelCompanies, companies);
                return orphaned.length > 0 ? [...groups, { key: 'orphaned', label: 'Other', companies: orphaned }] : groups;
              })();

        return (
          <div key={level} className="flex flex-col">
            {i > 0 && <LevelConnector />}
            <div className="mb-2 flex items-center gap-2">
              <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
              <p className="text-xs uppercase tracking-widest text-ink">{impactLevelLabel(level)}</p>
              <p className="text-xs text-muted">({levelCompanies.length})</p>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {cards.map((card) => (
                <ImpactCard
                  key={card.key}
                  label={card.label}
                  color={level === 'direct' ? sectorColor(card.key) : color}
                  signal={computeNetSignal(card.companies)}
                  companyCount={card.companies.length}
                >
                  {card.companies.map((c) => (
                    <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => toggle(c.company_id)} />
                  ))}
                </ImpactCard>
              ))}
            </div>
          </div>
        );
      })}
      {selected && (
        <div className="mt-4">
          <ReasoningPanel company={selected} eventType={eventType} />
        </div>
      )}
    </div>
  );
}
