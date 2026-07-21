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
        <ImpactTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} />
        <div className="border-t border-hairline">
          <LevelTree companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <ConfidenceTree companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <SplitTree companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <TimelineTree companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <SectorTree companies={alert.companies} eventType={alert.event_type} />
        </div>
      </div>
    </div>
  );
}
