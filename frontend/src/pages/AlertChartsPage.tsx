import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { getAlert, type Alert, type AlertCompany } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
import { computeNetSignal } from '../features/visualize/transforms';
import { impactLevelKey } from '../features/visualize/impactLevels';
import ImpactTree from '../features/visualize/charts/ImpactTree';

// --- Chart system disabled: blank slate, chart rebuild pending ---
// import { Link } from 'react-router-dom';
// import { useHorizontalSwipe } from '../lib/useHorizontalSwipe';
// import { groupBySector, rankByConfidence } from '../features/visualize/transforms';
// import { useCompanySelection } from '../features/visualize/charts/useCompanySelection';
// import ImpactCard from '../features/visualize/charts/cards/ImpactCard';
// import CompanyRow from '../features/visualize/charts/cards/CompanyRow';
// import ReasoningPanel from '../components/ReasoningPanel';
// import SectorTree from '../features/visualize/charts/SectorTree';
// import TierRows from '../features/visualize/charts/TierRows';
// import ImpactBar from '../features/visualize/charts/ImpactBar';
// import SplitTree from '../features/visualize/charts/SplitTree';
// import ConfidenceTree from '../features/visualize/charts/ConfidenceTree';
// import TimelineTree from '../features/visualize/charts/TimelineTree';
// import LevelTree, { type ForceCollapseSignal } from '../features/visualize/charts/LevelTree';
//
// const CHARTS = [
//   { key: 'levels', label: '1 · Impact Tree', Component: LevelTree },
//   { key: 'tier', label: 'Tier', Component: TierRows },
//   { key: 'impact', label: 'Impact', Component: ImpactBar },
//   { key: 'confidence', label: '5 · Confidence', Component: ConfidenceTree },
//   { key: 'split', label: '6 · Split', Component: SplitTree },
//   { key: 'timeline', label: '7 · Timeline', Component: TimelineTree },
//   { key: 'sector', label: '8 · Sector', Component: SectorTree },
// ] as const;
// --- end disabled chart system ---

// Normal = the article's own direct impact only (both actually-direct
// mentions and sector-inference fan-out -- see impact_level in
// app.analysis.schemas.IMPACT_LEVELS). Drilldown adds every company the
// model knows is economically linked through a supplier/customer/
// competitor chain (indirect_l1/indirect_l2), regardless of how deep.
type Breadth = 'normal' | 'drilldown';

function StatTile({ label, value, valueClass, caption }: { label: string; value: string; valueClass?: string; caption?: string }) {
  return (
    <div className="flex min-w-[7rem] flex-1 flex-col gap-1 rounded-xl border border-hairline p-3 theme-light:border-transparent theme-light:shadow-neu-sm">
      <p className="text-[11px] uppercase tracking-widest text-muted">{label}</p>
      <p className={`text-lg font-medium ${valueClass ?? 'text-ink'}`}>{value}</p>
      {caption && <p className="text-[11px] text-muted">{caption}</p>}
    </div>
  );
}

function StatBar({ companies, breadth }: { companies: AlertCompany[]; breadth: Breadth }) {
  const signal = computeNetSignal(companies);
  const sectorCount = new Set(companies.map((c) => c.sector).filter(Boolean)).size;
  const subSectorCount = new Set(companies.map((c) => c.sub_sector).filter(Boolean)).size;
  const levelCounts = { direct: 0, indirect_l1: 0, indirect_l2: 0 } as Record<string, number>;
  for (const c of companies) levelCounts[impactLevelKey(c)] += 1;

  const overallLabel = signal.direction === 'even' ? 'Mixed' : signal.direction === 'bullish' ? 'Bullish' : 'Bearish';
  const overallGlyph = signal.direction === 'even' ? '▬' : signal.direction === 'bullish' ? '▲' : '▼';
  const overallClass = signal.direction === 'even' ? 'text-muted' : signal.direction === 'bullish' ? 'text-bullish' : 'text-bearish';

  return (
    <div className="flex flex-wrap gap-2.5 border-b border-hairline p-4">
      <StatTile
        label="Overall Impact"
        value={`${overallGlyph} ${overallLabel}`}
        valueClass={overallClass}
        caption={`${signal.avgConfidence}% confidence`}
      />
      <StatTile label="Affected Sectors" value={String(sectorCount)} />
      <StatTile label="Affected Categories" value={String(subSectorCount)} caption={subSectorCount === 0 ? 'Unclassified' : undefined} />
      <StatTile label="Affected Companies" value={String(companies.length)} />
      {breadth === 'drilldown' && (
        <StatTile
          label="By Level"
          value={`${levelCounts.direct} / ${levelCounts.indirect_l1} / ${levelCounts.indirect_l2}`}
          caption="Direct / Indirect L1 / Indirect L2"
        />
      )}
    </div>
  );
}

// --- Chart system disabled: blank slate, chart rebuild pending ---
// function DirectlyAffectedSectors({
//   companies,
//   selectedId,
//   onSelect,
// }: {
//   companies: AlertCompany[];
//   selectedId: number | null;
//   onSelect: (id: number) => void;
// }) {
//   const sectors = groupBySector(companies);
//   if (sectors.length === 0) return null;
//
//   return (
//     <div className="flex flex-col gap-3 border-b border-hairline p-4">
//       <p className="text-xs uppercase tracking-widest text-muted">Directly Affected Sectors</p>
//       <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
//         {sectors.map((sector) => (
//           <ImpactCard
//             key={sector.key}
//             label={sector.label}
//             color={sector.color ?? '#557C30'}
//             signal={computeNetSignal(sector.companies)}
//             companyCount={sector.companies.length}
//             onViewDetails={() => onSelect(sector.companies[0].company_id)}
//           >
//             {sector.companies.map((c) => (
//               <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => onSelect(c.company_id)} />
//             ))}
//           </ImpactCard>
//         ))}
//       </div>
//     </div>
//   );
// }
//
// function ImpactSummaryBanner({ companies, alertId, title }: { companies: AlertCompany[]; alertId: number; title: string }) {
//   if (companies.length === 0) return null;
//   const sectors = groupBySector(companies);
//   const topSector = [...sectors].sort((a, b) => b.companies.length - a.companies.length)[0];
//   const top = rankByConfidence(companies)[0];
//   const signal = computeNetSignal(companies);
//   const outlook = signal.direction === 'even' ? 'a mixed' : signal.direction === 'bullish' ? 'a bullish' : 'a bearish';
//
//   return (
//     <div className="flex flex-col gap-2 border-b border-hairline p-4">
//       <p className="text-xs uppercase tracking-widest text-muted">{title}</p>
//       <p className="text-sm text-ink">
//         This event points to {outlook} outlook concentrated in {topSector.label} (
//         {topSector.companies.length} {topSector.companies.length === 1 ? 'company' : 'companies'}), at{' '}
//         {signal.avgConfidence}% average confidence.
//       </p>
//       <Link to={`/alerts/${alertId}/company/${top.company_id}`} className="self-start text-xs text-muted hover:text-ink">
//         View Full Analysis →
//       </Link>
//     </div>
//   );
// }
// --- end disabled chart system ---

export default function AlertChartsPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { token } = useAuth();
  const { language } = useLanguage();
  const [alert, setAlert] = useState<Alert | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [breadth, setBreadth] = useState<Breadth>('normal');

  // --- Chart system disabled: blank slate, chart rebuild pending ---
  // const [index, setIndex] = useState(0);
  // const [forceCollapse, setForceCollapse] = useState<ForceCollapseSignal | undefined>(undefined);
  // const [collapseVersion, setCollapseVersion] = useState(0);
  //
  // function expandAll() {
  //   const next = collapseVersion + 1;
  //   setCollapseVersion(next);
  //   setForceCollapse({ mode: 'expand', version: next });
  // }
  //
  // function collapseAll() {
  //   const next = collapseVersion + 1;
  //   setCollapseVersion(next);
  //   setForceCollapse({ mode: 'collapse', version: next });
  // }
  // --- end disabled chart system ---

  useEffect(() => {
    if (!id) return;
    let active = true;
    getAlert(Number(id), token, language)
      .then((data) => {
        if (active) setAlert(data);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'Failed to load alert.');
      });
    return () => {
      active = false;
    };
  }, [id, token, language]);

  // --- Chart system disabled: blank slate, chart rebuild pending ---
  // const swipeHandlers = useHorizontalSwipe({
  //   onSwipeLeft: () => setIndex((i) => Math.min(i + 1, CHARTS.length - 1)),
  //   onSwipeRight: () => (index === 0 ? navigate(-1) : setIndex((i) => Math.max(i - 1, 0))),
  // });
  // --- end disabled chart system ---

  // --- Chart system disabled: blank slate, chart rebuild pending ---
  // const { toggle, selected, selectedId } = useCompanySelection(visibleCompanies);
  // --- end disabled chart system ---

  if (error) {
    return <p className="p-4 text-xs uppercase tracking-widest text-bearish">{error}</p>;
  }
  if (!alert) {
    return <p className="p-4 text-xs uppercase tracking-widest text-muted">Loading…</p>;
  }

  // --- Chart system disabled: blank slate, chart rebuild pending ---
  // const { Component } = CHARTS[index];
  // --- end disabled chart system ---

  return (
    <div className="flex min-h-screen flex-col bg-page">
      <div className="flex items-center gap-3 border-b border-hairline p-4">
        <button type="button" onClick={() => navigate(-1)} aria-label="Back" className="text-muted hover:text-ink">
          ←
        </button>
        <h1 className="truncate text-sm text-ink">{alert.article.title}</h1>
        <div className="ml-auto flex gap-1 self-start rounded-md border border-hairline bg-surface p-0.5">
          {(['normal', 'drilldown'] as Breadth[]).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setBreadth(mode)}
              className={`rounded px-2 py-0.5 text-[11px] uppercase tracking-widest ${
                breadth === mode ? 'bg-page text-ink' : 'text-muted'
              }`}
            >
              {mode === 'normal' ? 'Normal' : 'Drilldown'}
            </button>
          ))}
        </div>
      </div>
      <StatBar companies={alert.companies} breadth={breadth} />
      <div className="flex-1 overflow-y-auto">
        <ImpactTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} />
        <div className="flex justify-center border-t border-hairline p-4">
          <Link
            to={`/alerts/${alert.id}/charts/cascade`}
            className="rounded-lg border border-hairline px-4 py-2 text-xs uppercase tracking-widest text-ink hover:bg-surface"
          >
            View Cascade Levels →
          </Link>
        </div>
      </div>
    </div>
  );
}
