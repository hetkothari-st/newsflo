import { useEffect, useRef, useState } from 'react';
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

// Normal = the article's own direct impact only (both actually-direct
// mentions and sector-inference fan-out -- see impact_level in
// app.analysis.schemas.IMPACT_LEVELS). Drilldown adds every company the
// model knows is economically linked through a supplier/customer/
// competitor chain (indirect_l1/indirect_l2), regardless of how deep.
type Breadth = 'normal' | 'drilldown';

const CHART_ITEMS = [
  { id: 'impact', label: '1. Impact Tree', shortName: 'Impact' },
  { id: 'ripple', label: '2. Ripple Effect', shortName: 'Ripple' },
  { id: 'supply_chain', label: '3. Supply Chain', shortName: 'Supply Chain' },
  { id: 'level', label: '4. Cascade Levels', shortName: 'Levels' },
  { id: 'confidence', label: '5. Confidence Tree', shortName: 'Confidence' },
  { id: 'split', label: '6. Positive/Negative Split', shortName: 'Split' },
  { id: 'timeline', label: '7. Timeline Tree', shortName: 'Timeline' },
  { id: 'sector', label: '8. Sector Tree', shortName: 'Sector' },
  { id: 'economic', label: '9. Economic Chain', shortName: 'Economic' },
  { id: 'knowledge', label: '10. Knowledge Graph', shortName: 'Knowledge' },
];

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
  const [activeIndex, setActiveIndex] = useState(0);

  const carouselRef = useRef<HTMLDivElement>(null);
  const tabsRef = useRef<HTMLDivElement>(null);

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

  const handleScroll = () => {
    if (!carouselRef.current) return;
    const container = carouselRef.current;
    const width = container.clientWidth;
    if (width > 0) {
      const index = Math.round(container.scrollLeft / width);
      if (index >= 0 && index < CHART_ITEMS.length && index !== activeIndex) {
        setActiveIndex(index);
      }
    }
  };

  const scrollToChart = (index: number) => {
    if (!carouselRef.current) return;
    const container = carouselRef.current;
    const width = container.clientWidth;
    container.scrollTo({ left: index * width, behavior: 'smooth' });
    setActiveIndex(index);
  };

  useEffect(() => {
    if (!tabsRef.current) return;
    const activeTab = tabsRef.current.children[activeIndex] as HTMLElement;
    if (activeTab) {
      activeTab.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    }
  }, [activeIndex]);

  if (error) {
    return <p className="p-4 text-xs uppercase tracking-widest text-bearish">{error}</p>;
  }
  if (!alert) {
    return <p className="p-4 text-xs uppercase tracking-widest text-muted">Loading…</p>;
  }

  const graph = buildGraph(alert);

  return (
    <div className="flex min-h-screen flex-col bg-page">
      {/* Top Navigation Bar with Main Feed Button */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-hairline p-4">
        <div className="flex items-center gap-3 min-w-0">
          <button
            type="button"
            onClick={() => navigate('/')}
            aria-label="Return to Main Feed"
            className="flex items-center gap-1.5 rounded-lg border border-hairline bg-surface px-3 py-1.5 text-xs font-semibold text-ink transition-colors hover:bg-page theme-light:border-transparent theme-light:shadow-neu-sm shrink-0"
          >
            <span aria-hidden="true">←</span>
            <span>Main Feed</span>
          </button>
          <button type="button" onClick={() => navigate(-1)} aria-label="Back" className="text-muted hover:text-ink text-xs uppercase tracking-widest px-1 shrink-0">
            Back
          </button>
          <h1 className="truncate text-sm text-ink font-medium">{alert.article.title}</h1>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex gap-1 rounded-md border border-hairline bg-surface p-0.5">
            {(['normal', 'drilldown'] as Breadth[]).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setBreadth(mode)}
                className={`rounded px-2 py-0.5 text-[11px] uppercase tracking-widest ${
                  breadth === mode ? 'bg-page text-ink font-semibold' : 'text-muted'
                }`}
              >
                {mode === 'normal' ? 'Normal' : 'Drilldown'}
              </button>
            ))}
          </div>
        </div>
      </div>

      <StatBar companies={alert.companies} breadth={breadth} />

      {/* Carousel Header & Controls */}
      <div className="border-b border-hairline bg-surface/50 px-4 py-2">
        <div className="mx-auto flex max-w-6xl flex-col gap-2">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="text-xs uppercase tracking-widest text-muted">
                Chart {activeIndex + 1} of {CHART_ITEMS.length}
              </span>
              <span className="text-xs font-medium text-ink">· {CHART_ITEMS[activeIndex].shortName}</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => scrollToChart(Math.max(0, activeIndex - 1))}
                disabled={activeIndex === 0}
                aria-label="Previous Chart"
                className="flex h-7 w-7 items-center justify-center rounded-md border border-hairline bg-surface text-ink disabled:opacity-30 disabled:cursor-not-allowed hover:bg-page"
              >
                ‹
              </button>
              <button
                type="button"
                onClick={() => scrollToChart(Math.min(CHART_ITEMS.length - 1, activeIndex + 1))}
                disabled={activeIndex === CHART_ITEMS.length - 1}
                aria-label="Next Chart"
                className="flex h-7 w-7 items-center justify-center rounded-md border border-hairline bg-surface text-ink disabled:opacity-30 disabled:cursor-not-allowed hover:bg-page"
              >
                ›
              </button>
            </div>
          </div>

          {/* Interactive Chart Selector Pill Tabs */}
          <div ref={tabsRef} className="no-scrollbar flex flex-nowrap items-center gap-1.5 overflow-x-auto py-1">
            {CHART_ITEMS.map((item, idx) => (
              <button
                key={item.id}
                type="button"
                onClick={() => scrollToChart(idx)}
                className={`shrink-0 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  activeIndex === idx
                    ? 'bg-ink text-page font-semibold'
                    : 'border border-hairline bg-surface text-muted hover:text-ink'
                }`}
              >
                {item.shortName}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Swipeable Cards Carousel Container */}
      <div className="flex-1 overflow-hidden py-4">
        <div className="mx-auto h-full max-w-6xl">
          <div
            ref={carouselRef}
            onScroll={handleScroll}
            className="no-scrollbar flex h-full w-full snap-x snap-mandatory overflow-x-auto scroll-smooth"
          >
            <div className="w-full shrink-0 snap-center px-4 overflow-y-auto max-h-full">
              <ImpactTree companies={alert.companies} graph={graph} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} />
            </div>
            <div className="w-full shrink-0 snap-center px-4 overflow-y-auto max-h-full">
              <RippleGraph graph={graph} companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} />
            </div>
            <div className="w-full shrink-0 snap-center px-4 overflow-y-auto max-h-full">
              <SupplyChainGraph graph={graph} companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} />
            </div>
            <div className="w-full shrink-0 snap-center px-4 overflow-y-auto max-h-full">
              <LevelTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} />
            </div>
            <div className="w-full shrink-0 snap-center px-4 overflow-y-auto max-h-full">
              <ConfidenceTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} />
            </div>
            <div className="w-full shrink-0 snap-center px-4 overflow-y-auto max-h-full">
              <SplitTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} />
            </div>
            <div className="w-full shrink-0 snap-center px-4 overflow-y-auto max-h-full">
              <TimelineTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} />
            </div>
            <div className="w-full shrink-0 snap-center px-4 overflow-y-auto max-h-full">
              <SectorTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} />
            </div>
            <div className="w-full shrink-0 snap-center px-4 overflow-y-auto max-h-full">
              <EconomicChain graph={graph} companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} />
            </div>
            <div className="w-full shrink-0 snap-center px-4 overflow-y-auto max-h-full">
              <KnowledgeGraph graph={graph} companies={alert.companies} eventType={alert.event_type} />
            </div>
          </div>
        </div>
      </div>

      {/* Footer Navigation Bar */}
      <div className="flex items-center justify-between border-t border-hairline bg-surface p-3 px-4 text-xs text-muted">
        <button
          type="button"
          onClick={() => navigate('/')}
          className="flex items-center gap-1.5 rounded-md border border-hairline bg-page px-3 py-1 text-ink font-medium hover:bg-surface"
        >
          ← Return to Main Feed
        </button>
        <span>Swipe left or right to switch charts</span>
      </div>
    </div>
  );
}

