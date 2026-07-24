import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getAlert, type Alert, type AlertCompany } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
import { computeNetSignal } from '../features/visualize/transforms';
import { impactLevelKey } from '../features/visualize/impactLevels';
import ImpactTree from '../features/visualize/charts/ImpactTree';
import LevelTree from '../features/visualize/charts/LevelTree';
import ConfidenceTree from '../features/visualize/charts/ConfidenceTree';
import SplitTree from '../features/visualize/charts/SplitTree';
import TimelineTree from '../features/visualize/charts/TimelineTree';
import SectorTree from '../features/visualize/charts/SectorTree';
import RippleGraph from '../features/visualize/charts/RippleGraph';
import SupplyChainGraph from '../features/visualize/charts/SupplyChainGraph';
import EconomicChain from '../features/visualize/charts/EconomicChain';
import KnowledgeGraph from '../features/visualize/charts/KnowledgeGraph';
import { buildGraph } from '../features/visualize/graph/model';
import { useHorizontalSwipe } from '../lib/useHorizontalSwipe';

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

export default function AlertChartsPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { token } = useAuth();
  const { language } = useLanguage();
  const [alert, setAlert] = useState<Alert | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [breadth, setBreadth] = useState<Breadth>('normal');
  const [activeChartIndex, setActiveChartIndex] = useState(0);

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

  if (error) {
    return <p className="p-4 text-xs uppercase tracking-widest text-bearish">{error}</p>;
  }
  if (!alert) {
    return <p className="p-4 text-xs uppercase tracking-widest text-muted">Loading…</p>;
  }

  const graph = buildGraph(alert);
  const charts = [
    { key: 'impact-tree', render: () => <ImpactTree companies={alert.companies} graph={graph} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'ripple-graph', render: () => <RippleGraph graph={graph} companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'supply-chain', render: () => <SupplyChainGraph graph={graph} companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'level-tree', render: () => <LevelTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'confidence-tree', render: () => <ConfidenceTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'split-tree', render: () => <SplitTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'timeline-tree', render: () => <TimelineTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'sector-tree', render: () => <SectorTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} /> },
    { key: 'economic-chain', render: () => <EconomicChain graph={graph} companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} /> },
    { key: 'knowledge-graph', render: () => <KnowledgeGraph graph={graph} companies={alert.companies} eventType={alert.event_type} /> },
  ];
  const goToPreviousChart = () => setActiveChartIndex((index) => Math.max(0, index - 1));
  const goToNextChart = () => setActiveChartIndex((index) => Math.min(charts.length - 1, index + 1));
  const swipeHandlers = useHorizontalSwipe({ onSwipeLeft: goToNextChart, onSwipeRight: goToPreviousChart });
  const activeChart = charts[activeChartIndex];

  return (
    <div className="flex min-h-screen flex-col bg-page">
      <div className="flex items-center gap-3 border-b border-hairline p-4">
        <button type="button" onClick={() => navigate(`/alerts/${id}`)} aria-label="Affected companies" className="text-muted hover:text-ink">
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
        <div className="mx-auto flex h-full w-full max-w-6xl flex-col px-4 py-4">
          <div
            data-testid="chart-carousel"
            className="flex min-h-0 flex-1 flex-col touch-pan-y"
            {...swipeHandlers}
          >
            <div className="mb-3 flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={goToPreviousChart}
                disabled={activeChartIndex === 0}
                aria-label="Previous chart"
                className="rounded-lg border border-hairline px-3 py-2 text-xs text-ink disabled:cursor-not-allowed disabled:opacity-40"
              >
                Previous
              </button>
              <p className="text-xs font-medium uppercase tracking-widest text-muted">Chart {activeChartIndex + 1} of {charts.length}</p>
              <button
                type="button"
                onClick={goToNextChart}
                disabled={activeChartIndex === charts.length - 1}
                aria-label="Next chart"
                className="rounded-lg border border-hairline px-3 py-2 text-xs text-ink disabled:cursor-not-allowed disabled:opacity-40"
              >
                Next
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto pr-0.5" key={activeChart.key}>
              {activeChart.render()}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
