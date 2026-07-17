import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { groupBySectorAndSubSector } from '../transforms';
import ImpactCard from './cards/ImpactCard';
import CompanyRow from './cards/CompanyRow';
import { useCompanySelection } from './useCompanySelection';

export default function SectorTree({
  companies,
  eventType,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const sectors = groupBySectorAndSubSector(companies);

  if (sectors.length === 0) return null;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {sectors.map((sector) => (
          <ImpactCard
            key={sector.key}
            label={sector.label}
            color={sector.color ?? '#557C30'}
            signal={sector.netSignal}
            companyCount={sector.companies.length}
          >
            {sector.subSectorGroups.length <= 1
              ? sector.companies.map((c) => (
                  <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => toggle(c.company_id)} />
                ))
              : sector.subSectorGroups.map((sub) => (
                  <div key={sub.key} className="flex flex-col gap-0.5">
                    <p className="px-2 pt-1.5 text-[11px] uppercase tracking-widest text-muted">{sub.label}</p>
                    {sub.companies.map((c) => (
                      <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => toggle(c.company_id)} />
                    ))}
                  </div>
                ))}
          </ImpactCard>
        ))}
      </div>
      {selected && <ReasoningPanel company={selected} eventType={eventType} />}
    </div>
  );
}
