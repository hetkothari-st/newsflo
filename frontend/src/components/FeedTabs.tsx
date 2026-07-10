export type FeedTab = 'india' | 'global' | 'custom';

const TABS: { key: FeedTab; label: string }[] = [
  { key: 'india', label: 'India' },
  { key: 'global', label: 'Global' },
  { key: 'custom', label: 'Custom' },
];

export default function FeedTabs({
  active,
  onChange,
}: {
  active: FeedTab;
  onChange: (tab: FeedTab) => void;
}) {
  return (
    <div className="mb-6 flex gap-6 border-b border-hairline" role="tablist" aria-label="Feed markets">
      {TABS.map((t) => {
        const isActive = t.key === active;
        return (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(t.key)}
            className={`border-b-2 pb-3 text-sm uppercase tracking-widest ${
              isActive ? 'border-ink text-ink' : 'border-transparent text-muted hover:text-ink'
            }`}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
