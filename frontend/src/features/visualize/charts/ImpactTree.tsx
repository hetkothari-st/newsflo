import type { AlertArticle, AlertCompany } from '../../../lib/api';
import { impactLevelKey } from '../impactLevels';
import { groupBySector, groupIndirectBySubSector, rankByConfidence, type CompanyGroup, type SubSectorGroup } from '../transforms';
import ChartCardShell from './ChartCardShell';

function truncatedRationale(rationale: string): string {
  const firstSentence = rationale.split(/(?<=[.!?])\s+/)[0];
  if (firstSentence.length <= 160) return firstSentence;
  return `${firstSentence.slice(0, 157)}…`;
}

function WhyExplanation({ companies }: { companies: AlertCompany[] }) {
  const top = rankByConfidence(companies)[0];
  return (
    <div className="flex max-w-md flex-col items-center gap-1 px-2 text-center">
      <span className="font-data text-[10px] uppercase tracking-widest text-muted">Why</span>
      <p className="font-editorial text-sm text-ink">{truncatedRationale(top.rationale)}</p>
    </div>
  );
}

function Connector() {
  return (
    <div aria-hidden="true" className="flex flex-col items-center text-muted">
      <span className="h-3 w-px bg-hairline" />
      <span className="text-xs leading-none">▼</span>
    </div>
  );
}

function EmptyLevelNote({ text }: { text: string }) {
  return <p className="px-1 font-data text-xs uppercase tracking-widest text-muted">{text}</p>;
}

function NewsNode({ article, alertCreatedAt }: { article: AlertArticle; alertCreatedAt: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-hairline p-4 theme-light:border-transparent theme-light:shadow-neu">
      <span className="font-data text-[11px] uppercase tracking-widest text-muted">News</span>
      <p className="font-editorial text-base text-ink">{article.title}</p>
      <span className="font-data text-[11px] text-muted">
        {new Date(alertCreatedAt).toLocaleString(undefined, {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        })}
      </span>
    </div>
  );
}

function LevelHeader({ level, name, count, color }: { level: string; name: string; count: number; color?: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-hairline px-3 py-2 theme-light:border-transparent theme-light:shadow-neu-sm">
      {color && <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />}
      <div className="flex flex-col">
        <span className="font-data text-[10px] uppercase tracking-widest text-muted">{level}</span>
        <span className="text-sm text-ink">
          {name} <span className="font-data text-xs text-muted">({count})</span>
        </span>
      </div>
    </div>
  );
}

function CompanyCard({ company }: { company: AlertCompany }) {
  const bearish = company.direction === 'bearish';
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-hairline p-2.5 theme-light:border-transparent theme-light:shadow-neu-sm">
      <span className="font-data text-xs font-semibold text-ink">{company.ticker}</span>
      <span className="truncate font-editorial text-sm text-ink">{company.name}</span>
      <span className={`font-data text-xs ${bearish ? 'text-bearish' : 'text-bullish'}`}>
        <span aria-hidden="true">{bearish ? '▼' : '▲'}</span> {company.confidence_score}%
      </span>
    </div>
  );
}

function SectorBlock({ sector }: { sector: CompanyGroup }) {
  return (
    <div className="flex w-full flex-col items-center gap-3">
      <LevelHeader level="Level 1 · Direct Impact" name={sector.label} count={sector.companies.length} color={sector.color} />
      <WhyExplanation companies={sector.companies} />
      <Connector />
      <p className="font-data text-[10px] uppercase tracking-widest text-muted">Level 2 · Companies</p>
      <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {sector.companies.map((c) => (
          <CompanyCard key={c.company_id} company={c} />
        ))}
      </div>
    </div>
  );
}

function SubSectorBlock({ subSector }: { subSector: SubSectorGroup }) {
  return (
    <div className="flex w-full flex-col items-center gap-3">
      <LevelHeader level="Level 3 · Indirect Ripple" name={subSector.label} count={subSector.companies.length} />
      <WhyExplanation companies={subSector.companies} />
      <Connector />
      <p className="font-data text-[10px] uppercase tracking-widest text-muted">Level 4 · Companies</p>
      <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {subSector.companies.map((c) => (
          <CompanyCard key={c.company_id} company={c} />
        ))}
      </div>
    </div>
  );
}

export default function ImpactTree({
  companies,
  article,
  alertCreatedAt,
}: {
  companies: AlertCompany[];
  article: AlertArticle;
  alertCreatedAt: string;
}) {
  const direct = companies.filter((c) => impactLevelKey(c) === 'direct');
  const sectorGroups = groupBySector(direct);
  const subSectorGroups = groupIndirectBySubSector(companies);

  return (
    <ChartCardShell
      number={1}
      title="Multi-Level Impact Tree"
      description="Sectors and companies affected, from direct impact down to indirect ripple effects"
    >
      <div className="flex flex-col items-center gap-4 p-4">
        <NewsNode article={article} alertCreatedAt={alertCreatedAt} />
        <Connector />
        {sectorGroups.length === 0 ? (
          <EmptyLevelNote text="No direct impact identified." />
        ) : (
          <div className="flex w-full flex-col gap-6">
            {sectorGroups.map((sector) => (
              <SectorBlock key={sector.key} sector={sector} />
            ))}
          </div>
        )}
        <div className="w-full border-t border-hairline" />
        {subSectorGroups.length === 0 ? (
          <EmptyLevelNote text="No indirect ripple effects identified." />
        ) : (
          <div className="flex w-full flex-col gap-6">
            {subSectorGroups.map((subSector) => (
              <SubSectorBlock key={subSector.key} subSector={subSector} />
            ))}
          </div>
        )}
      </div>
    </ChartCardShell>
  );
}
