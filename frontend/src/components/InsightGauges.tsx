import { useLanguage } from '../lib/language';
import { confidenceDotCount, horizonGlyph, horizonLabel, impactLabel } from '../lib/insightMappings';

export default function InsightGauges({
  confidenceScore,
  timeHorizon,
  impactLevel,
}: {
  confidenceScore: number;
  timeHorizon: string;
  impactLevel: string | undefined;
}) {
  const { language } = useLanguage();
  const filledDots = confidenceDotCount(confidenceScore);

  return (
    <div className="grid grid-cols-3 py-1.5">
      <div className="grid grid-rows-[auto_auto_20px] items-center justify-items-center gap-2">
        <span className="font-data text-[10.5px] uppercase tracking-widest text-bullish">Confidence</span>
        <span className="font-data text-[15px] font-semibold text-ink">{confidenceScore}%</span>
        <div className="flex items-center justify-center gap-1">
          {Array.from({ length: 5 }, (_, i) => (
            <span
              key={i}
              data-testid={i < filledDots ? 'confidence-dot-filled' : 'confidence-dot-empty'}
              className={`h-1.5 w-1.5 rounded-full ${i < filledDots ? 'bg-bullish' : 'bg-hairline'}`}
            />
          ))}
        </div>
      </div>
      <div className="grid grid-rows-[auto_auto_20px] items-center justify-items-center gap-2 border-l border-hairline">
        <span className="font-data text-[10.5px] uppercase tracking-widest text-muted">Horizon</span>
        <span className="font-data text-[15px] font-semibold text-ink">{horizonLabel(timeHorizon, language)}</span>
        <span className="flex items-center text-lg leading-none text-ink" aria-hidden="true">
          {horizonGlyph(timeHorizon)}
        </span>
      </div>
      <div className="grid grid-rows-[auto_auto_20px] items-center justify-items-center gap-2 border-l border-hairline">
        <span className="font-data text-[10.5px] uppercase tracking-widest text-muted">Impact</span>
        <span className="font-data text-[15px] font-semibold text-ink">{impactLabel(impactLevel, language)}</span>
        <span />
      </div>
    </div>
  );
}
