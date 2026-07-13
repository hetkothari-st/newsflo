import LiveStatus from './LiveStatus';

export type FeedTab = 'india' | 'global' | 'custom';

const TABS: { key: FeedTab; label: string }[] = [
  { key: 'india', label: 'India' },
  { key: 'global', label: 'Global' },
  { key: 'custom', label: 'Custom' },
];

export default function CategoryTabs({
  active,
  onChange,
  connected,
  lastAlertAt,
  newCount,
  onRevealNew,
  onOpenCustomSettings,
}: {
  active: FeedTab;
  onChange: (tab: FeedTab) => void;
  connected: boolean;
  lastAlertAt: string | null;
  newCount: number;
  onRevealNew: () => void;
  onOpenCustomSettings: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-lg border-b border-hairline p-2 theme-light:border-none theme-light:shadow-neu-sm">
      <div className="flex gap-6" role="tablist" aria-label="Feed markets">
        {TABS.map((t) => {
          const isActive = t.key === active;
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => onChange(t.key)}
              className={`border-b-2 pb-3 text-base font-bold uppercase tracking-widest motion-safe:transition-colors ${
                isActive ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-ink'
              }`}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      <div className="flex items-center gap-3 pb-3">
        {newCount > 0 && (
          <button
            type="button"
            onClick={onRevealNew}
            className="rounded-full border-[1.5px] border-bullish px-3 py-1 text-xs uppercase tracking-widest text-bullish"
          >
            {newCount} new
          </button>
        )}
        <LiveStatus connected={connected} lastAlertAt={lastAlertAt} />
        {active === 'custom' && (
          <button
            type="button"
            onClick={onOpenCustomSettings}
            aria-label="Custom feed settings"
            className="text-muted hover:text-ink"
          >
            ⚙
          </button>
        )}
      </div>
    </div>
  );
}
