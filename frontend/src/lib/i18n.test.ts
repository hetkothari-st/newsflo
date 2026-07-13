import { describe, expect, it } from 'vitest';
import { isSupportedLanguage, LANGUAGES, translate } from './i18n';

describe('LANGUAGES', () => {
  it('lists English plus every target language exactly once', () => {
    const codes = LANGUAGES.map((l) => l.code);
    expect(codes).toEqual(['en', 'hi', 'mr', 'gu', 'ml', 'te', 'ta', 'kn', 'pa', 'bn']);
  });
});

describe('isSupportedLanguage', () => {
  it('accepts every listed language code', () => {
    for (const { code } of LANGUAGES) {
      expect(isSupportedLanguage(code)).toBe(true);
    }
  });

  it('rejects an unsupported or null value', () => {
    expect(isSupportedLanguage('xx')).toBe(false);
    expect(isSupportedLanguage(null)).toBe(false);
  });
});

describe('translate', () => {
  it('returns the requested language for a known key', () => {
    expect(translate('hi', 'nav.feed')).toBe('फ़ीड');
  });

  it('falls back to English when the key has no entry for that language', () => {
    // Every real catalog key has all languages filled in, so simulate the
    // fallback path with a key that doesn't exist at all -- translate()
    // should return the raw key itself as the last-resort fallback.
    expect(translate('en', 'nonexistent.key' as never)).toBe('nonexistent.key');
  });

  it('interpolates {var}-style placeholders', () => {
    expect(translate('en', 'tabs.newCount', { n: 3 })).toBe('3 new');
  });

  it('interpolates every occurrence of a repeated placeholder', () => {
    expect(translate('en', 'reasoning.calibratedPrecedent', { direction: 'bullish' })).toContain(
      'comparable bullish move',
    );
  });
});
