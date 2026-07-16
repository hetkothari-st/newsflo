import { useLanguage } from '../lib/language';

// Same plain-stroke-icon convention as ThemeToggle -- inherits color via
// currentColor, no emoji/unicode glyph fallback risk.
function CalendarIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <path d="M16 2v4M8 2v4M3 10h18" />
    </svg>
  );
}

export default function CalendarButton({ onClick }: { onClick: () => void }) {
  const { t } = useLanguage();
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={t('nav.calendar')}
      className="flex h-8 w-8 items-center justify-center rounded-full text-muted outline-none transition-colors hover:text-ink focus-visible:ring-2 focus-visible:ring-accent theme-light:hover:shadow-neu-sm"
    >
      <CalendarIcon />
    </button>
  );
}
