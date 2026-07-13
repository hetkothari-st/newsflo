import { LANGUAGES } from '../lib/i18n';
import { useLanguage } from '../lib/language';

export default function TranslationProgressOverlay() {
  const { translating, translationProgress, language } = useLanguage();
  if (!translating) return null;

  const total = translationProgress?.total ?? 0;
  const done = translationProgress?.translated ?? 0;
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const nativeName = LANGUAGES.find((l) => l.code === language)?.label ?? language;

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 bg-page/95 px-6 backdrop-blur-sm"
    >
      <p className="text-xs uppercase tracking-widest text-muted">Translating news into {nativeName}…</p>
      <div className="h-2 w-64 max-w-[80vw] overflow-hidden rounded-full bg-hairline">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-300 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-xs tabular-nums text-muted">
        {done} / {total}
      </p>
    </div>
  );
}
