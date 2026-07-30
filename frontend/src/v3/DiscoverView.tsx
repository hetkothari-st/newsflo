/* Discovery (spec v2 §6): three entry paths as tabs -- materiality-ranked,
   related-to-holdings, unusual activity -- ranked by impact, never by
   headline prominence. Framing is factual: "most affected by news",
   never "best to buy". */
import { useEffect, useState } from 'react';
import { getDiscovery, type DiscoveryEntry, type DiscoveryTab } from './api';
import CompanyLogo from './CompanyLogo';
import { capClass, fmtPct, liqShort, moveColor } from './format';
import { useAuth } from '../lib/auth';

const TAB_LABELS: Record<DiscoveryTab, string> = {
  materiality: 'Materiality',
  holdings: 'Near holdings',
  unusual: 'Unusual activity',
};

function metricFor(entry: DiscoveryEntry, tab: DiscoveryTab): { text: string; color: string } {
  if (tab === 'unusual') {
    return {
      text: entry.volume_multiple != null ? `${entry.volume_multiple.toFixed(1)}× vol` : '—',
      color: 'var(--amber)',
    };
  }
  if (tab === 'holdings' && entry.excess_move_pct == null) {
    return { text: 'linked', color: 'var(--ink3)' };
  }
  return {
    text: entry.excess_move_pct != null ? fmtPct(entry.excess_move_pct) : '—',
    color: moveColor(entry.excess_move_pct),
  };
}

function matFor(
  entry: DiscoveryEntry,
  tab: DiscoveryTab,
  maxMateriality: number,
): { text: string; warn: boolean } {
  if (tab === 'holdings' && entry.via_ticker) return { text: `via ${entry.via_ticker}`, warn: false };
  if (entry.low_delivery && entry.delivery_pct != null) return { text: '⚠ low delivery', warn: true };
  if (tab === 'unusual' && entry.thin_trading) return { text: '⚠ thin trading', warn: true };
  if (entry.materiality != null && maxMateriality > 0) {
    // Normalized within this list (0-100), same within-population
    // discipline as every other sub-score (spec §4.2).
    return { text: `materiality ${Math.round((entry.materiality / maxMateriality) * 100)}`, warn: false };
  }
  return { text: '', warn: false };
}

export default function DiscoverView({
  active,
  onOpenDeepDive,
}: {
  active: boolean;
  onOpenDeepDive: (ticker: string, alertId?: number) => void;
}) {
  const { token } = useAuth();
  const [tab, setTab] = useState<DiscoveryTab>('materiality');
  const [entries, setEntries] = useState<DiscoveryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setEntries(null);
    setError(null);
    getDiscovery(tab, token)
      .then((result) => {
        if (!cancelled) setEntries(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [active, tab, token]);

  return (
    <div className={`view ${active ? 'on' : ''}`}>
      <div className="pagehd">
        <h2>Discover</h2>
        <p>Smaller names the headlines miss. Ranked by impact, not prominence.</p>
      </div>
      <div className="disctabs">
        {(Object.keys(TAB_LABELS) as DiscoveryTab[]).map((key) => (
          <button key={key} className={tab === key ? 'on' : ''} onClick={() => setTab(key)}>
            {TAB_LABELS[key]}
          </button>
        ))}
      </div>
      {error !== null && <p className="empty">{error}</p>}
      {entries !== null && entries.length === 0 && (
        <p className="empty">
          {tab === 'holdings'
            ? 'Nothing near your holdings today. Sign in and add holdings to see smaller names the same news touches.'
            : 'Nothing to surface yet today.'}
        </p>
      )}
      {entries?.map((entry) => {
        const metric = metricFor(entry, tab);
        const maxMateriality = Math.max(...(entries ?? []).map((e) => e.materiality ?? 0), 0);
        const mat = matFor(entry, tab, maxMateriality);
        return (
          <div
            className="dcard"
            key={`${entry.ticker}-${entry.alert_id}`}
            onClick={() => onOpenDeepDive(entry.ticker, entry.alert_id)}
          >
            <div className="dc-top">
              <CompanyLogo
                logoUrl={entry.logo_url}
                ticker={entry.ticker}
                sector={entry.sector}
                size="sm"
              />
              <span className="dc-name">{entry.name}</span>
              <span className="dc-metric" style={{ color: metric.color }}>
                {metric.text}
              </span>
            </div>
            <p className="dc-why">{entry.why ?? entry.headline}</p>
            <div className="dc-tags">
              <span className={`tag ${capClass(entry.cap_tier)}`}>{entry.cap_tier ?? '—'}</span>
              {entry.liquidity_tier !== null && (
                <span className={`liq liq-${liqShort(entry.liquidity_tier)}`}>
                  {liqShort(entry.liquidity_tier)}
                </span>
              )}
              <span className="dc-mat" style={mat.warn ? { color: 'var(--amber)' } : undefined}>
                {mat.text}
              </span>
            </div>
          </div>
        );
      })}
      <p className="aa-note">Framing is factual — "most affected by news", never "best to buy".</p>
    </div>
  );
}
