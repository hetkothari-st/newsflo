import type { TranslationKey } from '../lib/i18n';
import { useLanguage } from '../lib/language';
import LiveStatus from './LiveStatus';

export type FeedTab = 'india' | 'global' | 'custom';

const TABS: { key: FeedTab; labelKey: TranslationKey }[] = [
  { key: 'india', labelKey: 'tabs.india' },
  { key: 'global', labelKey: 'tabs.global' },
  { key: 'custom', labelKey: 'tabs.custom' },
];

export default function CategoryTabs({
  active,
  onChange,
  connected,
  newCount,
  onRevealNew,
  onOpenCustomSettings,
}: {
  active: FeedTab;
  onChange: (tab: FeedTab) => void;
  connected: boolean;
  newCount: number;
  onRevealNew: () => void;
  onOpenCustomSettings: () => void;
}) {
  const { t } = useLanguage();
  return (
    <div className="no-scrollbar flex flex-nowrap items-center justify-between gap-x-3 overflow-x-auto border-b border-hairline pt-3 theme-light:-mx-4 theme-light:border-none theme-light:px-4 theme-light:shadow-neu-sm md:theme-light:mx-0 md:theme-light:rounded-lg md:theme-light:p-2">
      <div className="flex shrink-0 gap-4 sm:gap-6" role="tablist" aria-label={t('tabs.marketsAria')}>
        {TABS.map((tab) => {
          const isActive = tab.key === active;
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => onChange(tab.key)}
              className={`border-b-2 pb-3 text-base font-bold uppercase tracking-widest motion-safe:transition-colors ${
                isActive ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-ink'
              }`}
            >
              {t(tab.labelKey)}
            </button>
          );
        })}
      </div>
      <div className="flex shrink-0 items-center gap-3 pb-3">
        {newCount > 0 && (
          <button
            type="button"
            onClick={onRevealNew}
            className="shrink-0 rounded-full border-[1.5px] border-bullish px-3 py-1 text-xs uppercase tracking-widest text-bullish"
          >
            {t('tabs.newCount', { n: newCount })}
          </button>
        )}
        <LiveStatus connected={connected} />
        {active === 'custom' && (
          <button
            type="button"
            onClick={onOpenCustomSettings}
            aria-label={t('tabs.customSettingsAria')}
            className="text-muted hover:text-ink"
          >
            ⚙
          </button>
        )}
      </div>
    </div>
  );
}
