import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { groupBySectorAndSubSector, type NetSignal } from '../transforms';
import { TreeRoot, TreeBranch, TreeLeaf } from './tree/Tree';
import { useCompanySelection } from './useCompanySelection';

// CSS custom properties (not literal hex) so the badge stays correct across
// light/dark theme without needing its own validated palette entry -- see
// frontend/src/index.css's --color-bullish/--color-bearish.
function signalBadge(signal: NetSignal): { text: string; color?: string } {
  if (signal.direction === 'even') return { text: `▬ ${signal.avgConfidence}%` };
  const bullish = signal.direction === 'bullish';
  return {
    text: `${bullish ? '▲' : '▼'} ${signal.avgConfidence}%`,
    color: bullish ? 'rgb(var(--color-bullish))' : 'rgb(var(--color-bearish))',
  };
}

export default function SectorTree({
  companies,
  eventType,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected } = useCompanySelection(companies);
  const sectors = groupBySectorAndSubSector(companies);

  if (sectors.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      <TreeRoot>
        {sectors.map((sector) => {
          const sectorBadge = signalBadge(sector.netSignal);
          return (
            <TreeBranch
              key={sector.key}
              label={sector.label}
              color={sector.color}
              badge={sectorBadge.text}
              badgeColor={sectorBadge.color}
            >
              {sector.subSectorGroups.length <= 1
                ? sector.companies.map((c) => (
                    <TreeLeaf key={c.company_id} ticker={c.ticker} direction={c.direction} onClick={() => toggle(c.company_id)} />
                  ))
                : sector.subSectorGroups.map((sub) => {
                    const subBadge = signalBadge(sub.netSignal);
                    return (
                      <TreeBranch
                        key={sub.key}
                        label={sub.label}
                        color={sector.color}
                        badge={subBadge.text}
                        badgeColor={subBadge.color}
                      >
                        {sub.companies.map((c) => (
                          <TreeLeaf key={c.company_id} ticker={c.ticker} direction={c.direction} onClick={() => toggle(c.company_id)} />
                        ))}
                      </TreeBranch>
                    );
                  })}
            </TreeBranch>
          );
        })}
      </TreeRoot>
      {selected && <ReasoningPanel company={selected} eventType={eventType} />}
    </div>
  );
}
