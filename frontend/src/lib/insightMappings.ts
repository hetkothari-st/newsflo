import type { Language } from './i18n';
import { translate } from './i18n';

export function confidenceDotCount(score: number): number {
  return Math.max(0, Math.min(5, Math.round(score / 20)));
}

const HORIZON_GLYPH: Record<string, string> = {
  Immediate: '●',
  'Short-Term': '◔',
  'Medium-Term': '◑',
  'Long-Term': '◯',
};

export function horizonGlyph(timeHorizon: string): string {
  return HORIZON_GLYPH[timeHorizon] ?? '◑';
}

const HORIZON_LABEL_KEY = {
  Immediate: 'insights.horizonImmediate',
  'Short-Term': 'insights.horizonShort',
  'Medium-Term': 'insights.horizonMedium',
  'Long-Term': 'insights.horizonLong',
} as const;

export function horizonLabel(timeHorizon: string, lang: Language): string {
  const key = HORIZON_LABEL_KEY[timeHorizon as keyof typeof HORIZON_LABEL_KEY];
  return key ? translate(lang, key) : timeHorizon;
}

export function impactLabel(level: string | undefined, lang: Language): string {
  if (level === 'indirect_l1') return translate(lang, 'insights.impactIndirect');
  if (level === 'indirect_l2') return translate(lang, 'insights.impactIndirectL2');
  return translate(lang, 'insights.impactDirect');
}
