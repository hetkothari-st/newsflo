import { LANGUAGES, type Language } from '../lib/i18n';
import { useLanguage } from '../lib/language';

// Options render each language's own native name (LANGUAGES' labels), never
// translated via t() -- a user who can't yet read the app's current language
// must still be able to find their own in this list.
export default function LanguagePicker() {
  const { language, setLanguage } = useLanguage();

  return (
    <select
      value={language}
      onChange={(e) => setLanguage(e.target.value as Language)}
      aria-label="Language"
      className="rounded-md border border-hairline bg-surface px-1.5 py-1 text-xs text-ink outline-none theme-light:border-transparent theme-light:shadow-neu-sm"
    >
      {LANGUAGES.map((l) => (
        <option key={l.code} value={l.code}>
          {l.label}
        </option>
      ))}
    </select>
  );
}
