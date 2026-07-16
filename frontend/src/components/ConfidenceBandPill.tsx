import { confidenceBandColor } from '../features/visualize/colors';
import { useLanguage } from '../lib/language';
import type { TranslationKey } from '../lib/i18n';

const BAND_LABEL_KEY: Record<string, TranslationKey> = {
  LOW: 'reasoning.confidenceLow',
  MODERATE: 'reasoning.confidenceModerate',
  HIGH: 'reasoning.confidenceHigh',
  VERY_HIGH: 'reasoning.confidenceVeryHigh',
};

export default function ConfidenceBandPill({ band }: { band: string | null | undefined }) {
  const { t } = useLanguage();
  if (!band) return null;
  const labelKey = BAND_LABEL_KEY[band];
  if (!labelKey) return null;
  const color = confidenceBandColor(band);
  return (
    <span
      className="ml-1.5 inline-flex items-center rounded-full border-[1.5px] px-2 py-0.5 text-[10px] uppercase tracking-widest"
      style={{ borderColor: color, color }}
    >
      {t(labelKey)}
    </span>
  );
}
