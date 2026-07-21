import { useMemo, useState } from 'react';
import type { AlertCompany } from '../../../lib/api';
import { IMPACT_LEVEL_ORDER, impactLevelColor, impactLevelKey, impactLevelLabel } from '../impactLevels';
import ChartCardShell from './ChartCardShell';
import CompanyCard from './cards/CompanyCard';

function LevelConnector() {
  return (
    <div aria-hidden="true" className="flex justify-center py-0.5">
      <span className="text-muted">↓</span>
    </div>
  );
}

// Click-to-reveal detail for a cascade company: which company it chains
// from, plus one short, plain-language key_point explaining why -- never
// the full rationale paragraph. Direct-level companies have no parent so
// never render this (see the `isCascade` gate where it's used).
function CompanyDetail({ company, parent }: { company: AlertCompany; parent?: AlertCompany }) {
  const point = company.key_points?.[0];
  if (!parent && !point) return null;
  return (
    <div className="mt-1 flex flex-col gap-1 rounded-lg border border-hairline bg-surface p-2.5">
      {parent && (
        <p className="font-data text-[10px] uppercase tracking-widest text-muted">
          Linked via {parent.ticker} · {parent.name}
        </p>
      )}
      {point && <p className="text-xs text-ink">{point}</p>}
    </div>
  );
}

const LEGEND = [
  { label: impactLevelLabel('direct'), color: impactLevelColor('direct') },
  { label: impactLevelLabel('indirect_l1'), color: impactLevelColor('indirect_l1') },
  { label: impactLevelLabel('indirect_l2'), color: impactLevelColor('indirect_l2') },
];

export default function LevelTree({ companies }: { companies: AlertCompany[] }) {
  const byId = useMemo(() => new Map(companies.map((c) => [c.company_id, c])), [companies]);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const levels = useMemo(
    () =>
      IMPACT_LEVEL_ORDER.map((level) => ({
        level,
        companies: companies.filter((c) => impactLevelKey(c) === level),
      })).filter((l) => l.companies.length > 0),
    [companies],
  );

  if (levels.length === 0) return null;

  return (
    <ChartCardShell
      number={2}
      title="Cascade Levels"
      description="Companies affected at each cascade level -- direct, and the ripple effects it triggers"
      legend={LEGEND}
    >
      <div className="flex flex-col p-4">
        {levels.map(({ level, companies: levelCompanies }, i) => {
          const color = impactLevelColor(level);
          const isCascade = level !== 'direct';
          return (
            <div key={level} className="flex flex-col">
              {i > 0 && <LevelConnector />}
              <div className="mb-2 flex items-center gap-2">
                <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
                <p className="text-xs uppercase tracking-widest text-ink">{impactLevelLabel(level)}</p>
                <p className="text-xs text-muted">({levelCompanies.length})</p>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {levelCompanies.map((c) => {
                  const selected = selectedId === c.company_id;
                  return (
                    <div key={c.company_id} className="flex flex-col">
                      <CompanyCard
                        company={c}
                        showSector
                        selected={selected}
                        onClick={isCascade ? () => setSelectedId(selected ? null : c.company_id) : undefined}
                      />
                      {isCascade && selected && (
                        <CompanyDetail
                          company={c}
                          parent={c.parent_company_id != null ? byId.get(c.parent_company_id) : undefined}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </ChartCardShell>
  );
}
