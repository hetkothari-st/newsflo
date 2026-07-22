import type { AlertArticle, AlertCompany, ImpactGraph } from '../../../lib/api';
import { impactLevelKey } from '../impactLevels';
import { groupBySector, groupIndirectBySubSector, rankByConfidence, type CompanyGroup, type SubSectorGroup } from '../transforms';
import ChartCardShell from './ChartCardShell';
import ReasoningPanel from '../../../components/ReasoningPanel';
import CompanyNode from './primitives/CompanyNode';
import ElbowConnector from './primitives/ElbowConnector';
import LevelBand from './primitives/LevelBand';
import NewsHeaderBlock from './primitives/NewsHeaderBlock';
import { useCompanySelection } from './useCompanySelection';

function truncatedRationale(rationale: string): string {
  const firstSentence = rationale.split(/(?<=[.!?])\s+/)[0];
  if (firstSentence.length <= 160) return firstSentence;
  return `${firstSentence.slice(0, 157)}…`;
}

// The real, per-article, sector-level reasoning (backend
// app.analysis.cascade._sector_mechanism_edges) -- a dedicated news->sector
// edge whose note is the sector's own "why is this sector affected" text,
// not any one company's rationale. Reported live bug: this WHY block used
// to show the highest-confidence COMPANY's own rationale as if it were the
// sector's explanation, misleading whenever companies in the same sector
// had different individual angles.
function sectorMechanism(graph: ImpactGraph | undefined, sectorKey: string | undefined): string | null {
  if (!graph || !sectorKey) return null;
  const edge = graph.edges.find((e) => e.from === 'news' && e.to === `sector:${sectorKey}`);
  return edge?.note ?? null;
}

function WhyExplanation({ companies, mechanism }: { companies: AlertCompany[]; mechanism: string | null }) {
  // Fallback to the top company's own rationale only when no sector-level
  // edge exists at all (shouldn't normally happen -- _build_graph's root-
  // backfill guarantees a news->sector edge -- but never show a blank WHY).
  const top = rankByConfidence(companies)[0];
  const text = mechanism ?? truncatedRationale(top.rationale);
  return (
    <div className="flex max-w-md flex-col items-center gap-1 px-2 text-center">
      <span className="font-data text-[10px] uppercase tracking-widest text-muted">Why</span>
      <p className="font-editorial text-sm text-ink">{text}</p>
    </div>
  );
}

function EmptyLevelNote({ text }: { text: string }) {
  return <p className="px-1 font-data text-xs uppercase tracking-widest text-muted">{text}</p>;
}

// Sector/sub-sector identity sits above its LevelBand rather than inside
// the band's own label -- a sector name needs to stay independently
// queryable ("Banking" alone, not "Level 1 · Direct Impact · Banking"),
// and this chart can have more than one sector's band at the same level.
function GroupHeading({ level, label, count, color }: { level: string; label: string; count: number; color?: string }) {
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className="font-data text-[10px] uppercase tracking-widest text-muted">{level}</span>
      <div className="flex items-center gap-2">
        {color && <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />}
        <span className="text-sm text-ink">
          {label} <span className="font-data text-xs text-muted">({count})</span>
        </span>
      </div>
    </div>
  );
}

function CompanyNodeRow({
  companies, selectedId, onToggle,
}: {
  companies: AlertCompany[]; selectedId: number | null; onToggle: (id: number) => void;
}) {
  return (
    <>
      {companies.map((c) => (
        <CompanyNode
          key={c.company_id}
          name={c.name}
          ticker={c.ticker}
          direction={c.direction}
          magnitudeLow={c.magnitude_low}
          magnitudeHigh={c.magnitude_high}
          inMyHoldings={c.in_my_holdings}
          onClick={() => onToggle(c.company_id)}
          selected={selectedId === c.company_id}
        />
      ))}
    </>
  );
}

function SectorBlock({
  sector, graph, selectedId, onToggle,
}: {
  sector: CompanyGroup; graph: ImpactGraph; selectedId: number | null; onToggle: (id: number) => void;
}) {
  return (
    <div className="flex w-full flex-col items-center gap-3">
      <GroupHeading level="Level 1 · Direct Impact" label={sector.label} count={sector.companies.length} color={sector.color} />
      <WhyExplanation companies={sector.companies} mechanism={sectorMechanism(graph, sector.key)} />
      <ElbowConnector />
      <LevelBand label="Level 2 · Companies">
        <CompanyNodeRow companies={sector.companies} selectedId={selectedId} onToggle={onToggle} />
      </LevelBand>
    </div>
  );
}

function SubSectorBlock({
  subSector, graph, selectedId, onToggle,
}: {
  subSector: SubSectorGroup; graph: ImpactGraph; selectedId: number | null; onToggle: (id: number) => void;
}) {
  // A sub-sector (e.g. "NBFC") isn't itself a SectorFinding -- fall back to
  // its companies' own (shared, in the normal case) parent sector to find
  // the real mechanism edge for that broader sector.
  const sectorKey = subSector.companies[0]?.sector;
  return (
    <div className="flex w-full flex-col items-center gap-3">
      <GroupHeading level="Level 3 · Indirect Ripple" label={subSector.label} count={subSector.companies.length} />
      <WhyExplanation companies={subSector.companies} mechanism={sectorMechanism(graph, sectorKey)} />
      <ElbowConnector />
      <LevelBand label="Level 4 · Companies">
        <CompanyNodeRow companies={subSector.companies} selectedId={selectedId} onToggle={onToggle} />
      </LevelBand>
    </div>
  );
}

export default function ImpactTree({
  companies,
  graph,
  article,
  alertCreatedAt,
  eventType,
}: {
  companies: AlertCompany[];
  graph: ImpactGraph;
  article: AlertArticle;
  alertCreatedAt: string;
  eventType?: string | null;
}) {
  const direct = companies.filter((c) => impactLevelKey(c) === 'direct');
  const sectorGroups = groupBySector(direct);
  const subSectorGroups = groupIndirectBySubSector(companies);
  const { toggle, selected, selectedId } = useCompanySelection(companies);

  return (
    <ChartCardShell
      number={1}
      title="Multi-Level Impact Tree"
      description="Sectors and companies affected, from direct impact down to indirect ripple effects"
      accentColor="#E85D4C"
    >
      <div className="flex flex-col items-center gap-4">
        <NewsHeaderBlock article={article} alertCreatedAt={alertCreatedAt} />
        <ElbowConnector />
        {sectorGroups.length === 0 ? (
          <EmptyLevelNote text="No direct impact identified." />
        ) : (
          <div className="flex w-full flex-col gap-6">
            {sectorGroups.map((sector) => (
              <SectorBlock key={sector.key} sector={sector} graph={graph} selectedId={selectedId} onToggle={toggle} />
            ))}
          </div>
        )}
        <div className="w-full border-t border-hairline" />
        {subSectorGroups.length === 0 ? (
          <EmptyLevelNote text="No indirect ripple effects identified." />
        ) : (
          <div className="flex w-full flex-col gap-6">
            {subSectorGroups.map((subSector) => (
              <SubSectorBlock key={subSector.key} subSector={subSector} graph={graph} selectedId={selectedId} onToggle={toggle} />
            ))}
          </div>
        )}
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
