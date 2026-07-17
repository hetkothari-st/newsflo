import { useEffect, useMemo, useRef, useState } from 'react';
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { computeNetSignal, groupBySector } from '../transforms';
import { sectorColor } from '../colors';
import { IMPACT_LEVEL_ORDER, impactLevelColor, impactLevelKey, impactLevelLabel } from '../impactLevels';
import ChartCardShell from './ChartCardShell';
import ImpactCard from './cards/ImpactCard';
import CompanyRow from './cards/CompanyRow';
import { useCompanySelection } from './useCompanySelection';

export interface ForceCollapseSignal {
  mode: 'expand' | 'collapse';
  version: number;
}

interface LevelCard {
  key: string;
  label: string;
  companies: AlertCompany[];
  sectorKey?: string;
}

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

const LEGEND = [
  { label: impactLevelLabel('direct'), color: impactLevelColor('direct') },
  { label: impactLevelLabel('indirect_l1'), color: impactLevelColor('indirect_l1') },
  { label: impactLevelLabel('indirect_l2'), color: impactLevelColor('indirect_l2') },
];

export default function LevelTree({
  companies,
  eventType,
  forceCollapse,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
  forceCollapse?: ForceCollapseSignal;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);

  const levels = useMemo(() => {
    return IMPACT_LEVEL_ORDER.map((level) => {
      const levelCompanies = companies.filter((c) => impactLevelKey(c) === level);
      let cards: LevelCard[];
      if (level === 'direct') {
        cards = groupBySector(levelCompanies).map((g) => ({ key: g.key, label: g.label, companies: g.companies, sectorKey: g.key }));
      } else {
        const { groups, orphaned } = groupByParent(levelCompanies, companies);
        cards = groups.map((g) => ({ key: `${level}-${g.key}`, label: g.label, companies: g.companies }));
        if (orphaned.length > 0) cards.push({ key: `${level}-orphaned`, label: 'Other', companies: orphaned });
      }
      return { level, companies: levelCompanies, cards };
    }).filter((l) => l.companies.length > 0);
  }, [companies]);

  const [collapsedKeys, setCollapsedKeys] = useState<Set<string>>(new Set());
  const lastVersion = useRef(0);

  useEffect(() => {
    if (!forceCollapse || forceCollapse.version === lastVersion.current) return;
    lastVersion.current = forceCollapse.version;
    if (forceCollapse.mode === 'collapse') {
      setCollapsedKeys(new Set(levels.flatMap((l) => l.cards.map((c) => c.key))));
    } else {
      setCollapsedKeys(new Set());
    }
  }, [forceCollapse, levels]);

  function toggleCard(key: string) {
    setCollapsedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  if (levels.length === 0) return null;

  return (
    <ChartCardShell
      number={1}
      title="Impact Tree"
      description="Hierarchical tree showing primary, secondary, and tertiary affected companies"
      legend={LEGEND}
    >
      <div className="flex flex-col p-4">
        {levels.map(({ level, companies: levelCompanies, cards }, i) => {
          const color = impactLevelColor(level);
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
                    color={card.sectorKey ? sectorColor(card.sectorKey) : color}
                    signal={computeNetSignal(card.companies)}
                    companyCount={card.companies.length}
                    collapsed={collapsedKeys.has(card.key)}
                    onToggle={() => toggleCard(card.key)}
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
    </ChartCardShell>
  );
}
