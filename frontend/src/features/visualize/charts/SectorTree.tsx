import type { AlertArticle, AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { groupBySectorAndSubSector } from '../transforms';
import ChartCardShell from './ChartCardShell';
import ImpactCard from './cards/ImpactCard';
import CompanyRow from './cards/CompanyRow';
import NewsHeaderBlock from './primitives/NewsHeaderBlock';
import { useCompanySelection } from './useCompanySelection';

export default function SectorTree({
  companies,
  article,
  alertCreatedAt,
  eventType,
}: {
  companies: AlertCompany[];
  article: AlertArticle;
  alertCreatedAt: string;
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const sectors = groupBySectorAndSubSector(companies);

  if (sectors.length === 0) return null;

  return (
    <ChartCardShell number={8} title="Sector Tree" description="Impact organized by sectors and sub-sectors" accentColor="#557C30">
      <div className="flex flex-col items-center gap-4">
        <NewsHeaderBlock article={article} alertCreatedAt={alertCreatedAt} />
        <div className="grid w-full grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
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
    </ChartCardShell>
  );
}
