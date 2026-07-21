import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
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

const LEGEND = [
  { label: impactLevelLabel('direct'), color: impactLevelColor('direct') },
  { label: impactLevelLabel('indirect_l1'), color: impactLevelColor('indirect_l1') },
  { label: impactLevelLabel('indirect_l2'), color: impactLevelColor('indirect_l2') },
];

// alertId is required -- every company card navigates to its full
// reasoning page (/alerts/:alertId/company/:companyId) on click, which
// needs the alert id LevelTree itself never otherwise receives (a plain
// AlertCompany carries its own company_id but not its parent alert's id).
export default function LevelTree({ alertId, companies }: { alertId: number; companies: AlertCompany[] }) {
  const navigate = useNavigate();

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
          return (
            <div key={level} className="flex flex-col">
              {i > 0 && <LevelConnector />}
              <div className="mb-2 flex items-center gap-2">
                <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
                <p className="text-xs uppercase tracking-widest text-ink">{impactLevelLabel(level)}</p>
                <p className="text-xs text-muted">({levelCompanies.length})</p>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {levelCompanies.map((c) => (
                  <CompanyCard
                    key={c.company_id}
                    company={c}
                    showSector
                    onClick={() => navigate(`/alerts/${alertId}/company/${c.company_id}`)}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </ChartCardShell>
  );
}
