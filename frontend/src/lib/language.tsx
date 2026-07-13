import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { isSupportedLanguage, translate, type Language, type TranslationKey } from './i18n';
import { getTranslationStatus, triggerTranslation, type TranslationStatus } from './api';

interface LanguageContextValue {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string;
  // Whether an on-demand translation drain is in flight for the current
  // language switch, and its last-polled progress -- drives
  // TranslationProgressOverlay. Both stay at their idle defaults for
  // English (nothing to translate).
  translating: boolean;
  translationProgress: TranslationStatus | null;
}

const LANG_KEY = 'newsflo.lang';
const POLL_INTERVAL_MS = 1200;
const MAX_POLLS = 150; // ~3 minutes safety cap in case a drain hangs

const LanguageContext = createContext<LanguageContextValue | null>(null);

function readStoredLanguage(): Language {
  const stored = localStorage.getItem(LANG_KEY);
  return isSupportedLanguage(stored) ? stored : 'en';
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(readStoredLanguage);
  const [translating, setTranslating] = useState(false);
  const [translationProgress, setTranslationProgress] = useState<TranslationStatus | null>(null);
  // Bumped on every setLanguage call so a poll loop left over from a
  // previous switch recognizes it's obsolete and stops touching state --
  // otherwise a quick switch en -> hi -> mr could have hi's late-arriving
  // poll response overwrite mr's progress.
  const pollGeneration = useRef(0);

  const setLanguage = useCallback((lang: Language) => {
    localStorage.setItem(LANG_KEY, lang);
    setLanguageState(lang);
    const generation = ++pollGeneration.current;

    if (lang === 'en') {
      setTranslating(false);
      setTranslationProgress(null);
      return;
    }

    setTranslating(true);
    setTranslationProgress(null);

    (async () => {
      try {
        await triggerTranslation(lang);
        for (let i = 0; i < MAX_POLLS; i++) {
          if (pollGeneration.current !== generation) return;
          const status = await getTranslationStatus(lang);
          if (pollGeneration.current !== generation) return;
          setTranslationProgress(status);
          if (!status.running) break;
          await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        }
      } catch {
        // Best-effort UI only -- whatever isn't translated yet silently
        // falls back to English regardless (see backend translation/lookup.py).
      } finally {
        if (pollGeneration.current === generation) setTranslating(false);
      }
    })();
  }, []);

  const t = useCallback(
    (key: TranslationKey, vars?: Record<string, string | number>) => translate(language, key, vars),
    [language],
  );

  return (
    <LanguageContext.Provider value={{ language, setLanguage, t, translating, translationProgress }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext);
  if (ctx === null) {
    throw new Error('useLanguage must be used within a LanguageProvider');
  }
  return ctx;
}
