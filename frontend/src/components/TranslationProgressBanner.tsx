import { useEffect, useState } from 'react';
import { LANGUAGES } from '../lib/i18n';
import { useLanguage } from '../lib/language';

// Rendered in normal document flow (not `fixed`/`absolute`) above NavBar, so
// it never overlays or blocks anything -- the rest of the app stays fully
// navigable and usable while a translation drain runs in the background.
export default function TranslationProgressBanner() {
  const { translating, translationProgress, language, translationRequestId } = useLanguage();
  const [dismissed, setDismissed] = useState(false);

  // A fresh switch should show the banner again even if a previous one was
  // dismissed -- keyed on translationRequestId (bumped on every switch),
  // not `translating`, since re-selecting the same language while a prior
  // drain is still in flight never flips `translating` false in between.
  useEffect(() => {
    setDismissed(false);
  }, [translationRequestId]);

  if (!translating || dismissed) return null;

  const total = translationProgress?.total ?? 0;
  const done = translationProgress?.translated ?? 0;
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const nativeName = LANGUAGES.find((l) => l.code === language)?.label ?? language;

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-3 border-b border-hairline bg-surface px-4 py-2"
    >
      <span className="whitespace-nowrap text-xs uppercase tracking-widest text-muted">
        Translating into {nativeName}…
      </span>
      <div className="h-1.5 w-full max-w-xs overflow-hidden rounded-full bg-hairline">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-300 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="whitespace-nowrap text-xs tabular-nums text-muted">
        {done} / {total}
      </span>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="Dismiss"
        className="ml-auto text-muted hover:text-ink"
      >
        ✕
      </button>
    </div>
  );
}
