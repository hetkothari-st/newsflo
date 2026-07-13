import { useLanguage } from '../lib/language';

export default function LiveStatus({ connected }: { connected: boolean }) {
  const { t } = useLanguage();
  return (
    <div className="flex shrink-0 items-center gap-2 whitespace-nowrap text-xs uppercase tracking-widest">
      <span className="relative flex h-2 w-2">
        {connected && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-bullish opacity-75 motion-reduce:hidden" />
        )}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${connected ? 'bg-bullish' : 'bg-muted'}`} />
      </span>
      <span className={connected ? 'text-ink' : 'text-muted'}>{connected ? t('live.live') : t('live.reconnecting')}</span>
    </div>
  );
}
