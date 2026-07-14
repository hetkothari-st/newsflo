import type { AlertCompany } from './api';
import { translate, type Language } from './i18n';

export function formatMentionDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

// Spec fallback rule: once the calibration DB has enough samples the confidence
// is "calibrated" and the direction is framed as historical precedent;
// otherwise the LLM's own estimate stands. Magnitude percentages are
// deliberately not shown -- they're frequently inaccurate and would overstate
// precision the model doesn't actually have.
//
// `lang` defaults to English so this stays a plain, providerless pure
// function for callers/tests that don't care about localization -- callers
// pass the viewer's actual language via useLanguage().
export function precedentLine(company: AlertCompany, lang: Language = 'en'): string {
  if (company.confidence === 'calibrated') {
    const direction = translate(lang, company.direction === 'bullish' ? 'reasoning.bullish' : 'reasoning.bearish');
    return translate(lang, 'reasoning.calibratedPrecedent', { direction });
  }
  return translate(lang, 'reasoning.noCalibratedHistory');
}

// The model's rationale is a full paragraph (deliberately kept rich -- that
// depth is the point). Splitting it into one bullet per sentence keeps every
// word but makes it scannable instead of a wall of text. Sentence-boundary
// heuristic (period/!/? followed by a capital letter), not real NLP -- good
// enough for display, and a mis-split just means two bullets instead of one.
export function splitRationaleIntoPoints(rationale: string): string[] {
  return rationale
    .split(/(?<=[.!?])\s+(?=[A-Z(])/)
    .map((point) => point.trim())
    .filter(Boolean);
}
