import type { AlertArticle, AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { useCompanySelection } from '../charts/useCompanySelection';
import { groupBySectorAndSubSector, rankByMove } from '../transforms';
import DeckChartFrame from './DeckChartFrame';
import DeckCompanyRow from './DeckCompanyRow';
import { formatPct, meanMove } from './deckData';
import './deck.css';

// Chart 8 -- Sector Tree (Doc-1 §4). Companies grouped by sector; within a
// sector, sub-grouped by sub_sector only when that adds information (more
// than one distinct sub-sector present). The mean move is computed over
// MEASURED moves only and omitted entirely when nothing in the sector has
// been measured -- never a fabricated 0%.
export default function DeckSectors({
  companies,
  article: _article,
  alertCreatedAt: _alertCreatedAt,
  eventType,
  displayNumber = 8,
}: {
  companies: AlertCompany[];
  article: AlertArticle;
  alertCreatedAt: string;
  eventType?: string | null;
  displayNumber?: number;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const sectors = groupBySectorAndSubSector(companies);

  return (
    <DeckChartFrame
      number={displayNumber}
      title="Sector Tree"
      description="The same companies regrouped by sector, with each sector's mean measured move."
      legend={sectors.map((s) => ({ label: s.label, color: s.color ?? 'rgb(var(--color-muted))' }))}
    >
      {sectors.map((sector) => {
        const mean = meanMove(sector.companies);
        const showSubSectors = sector.subSectorGroups.length > 1;
        return (
          <div key={sector.key} className="deck-sectorpanel">
            <span className="deck-groupheader">
              <span className="deck-sectordot" style={{ background: sector.color }} aria-hidden="true" />
              {sector.label}
              <span className="deck-groupsub"> · {sector.companies.length}</span>
              {mean != null && <span className="deck-groupsub"> · mean {formatPct(mean)}</span>}
            </span>
            {showSubSectors
              ? sector.subSectorGroups.map((sub) => (
                  <div key={sub.key} className="deck-subsector">
                    <span className="deck-groupheader deck-subsectorheader">
                      {sub.label}
                      <span className="deck-groupsub"> · {sub.companies.length}</span>
                    </span>
                    {rankByMove(sub.companies).map((c) => (
                      <DeckCompanyRow key={c.company_id} company={c} onClick={() => toggle(c.company_id)} selected={selectedId === c.company_id} />
                    ))}
                  </div>
                ))
              : rankByMove(sector.companies).map((c) => (
                  <DeckCompanyRow key={c.company_id} company={c} onClick={() => toggle(c.company_id)} selected={selectedId === c.company_id} />
                ))}
          </div>
        );
      })}
      {selected && <ReasoningPanel company={selected} eventType={eventType} />}
    </DeckChartFrame>
  );
}
