import { useLanguage } from '../../../lib/language';
import type { AlertArticle, AlertCompany } from '../../../lib/api';
import { BAND_LABEL_KEY } from '../../../components/ConfidenceBandPill';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { rankByConfidence } from '../transforms';
import { confidenceBandColor, confidenceBandFromScore } from '../colors';
import ChartCardShell from './ChartCardShell';
import CompanyNode from './primitives/CompanyNode';
import LevelBand from './primitives/LevelBand';
import NewsHeaderBlock from './primitives/NewsHeaderBlock';
import { useCompanySelection } from './useCompanySelection';

// Highest-confidence band first -- matches the mockup's Confidence Tree,
// which reads top-to-bottom as High -> Medium -> Low Confidence.
const BAND_ORDER = ['VERY_HIGH', 'HIGH', 'MODERATE', 'LOW'] as const;

// The real HIGH/MODERATE boundary confidenceBandFromScore already uses
// (see colors.ts) -- not a fabricated number, the same 70 that decides
// which band a company actually lands in.
const CONFIDENCE_THRESHOLD = 70;

export default function ConfidenceTree({
  companies,
  article,
  alertCreatedAt,
  eventType,
}: {
  companies: AlertCompany[];
  article: AlertArticle;
  alertCreatedAt: string;
  eventType?: string | null;
}) {
  const { t } = useLanguage();
  const { toggle, selected, selectedId } = useCompanySelection(companies);

  if (companies.length === 0) return null;

  const groups = BAND_ORDER.map((band) => ({
    band,
    companies: rankByConfidence(companies.filter((c) => confidenceBandFromScore(c.confidence_score) === band)),
  })).filter((g) => g.companies.length > 0);

  return (
    <ChartCardShell
      number={5}
      title="Confidence Tree"
      description="Tree showing companies with confidence scores for impact"
      legend={groups.map((g) => ({ label: t(BAND_LABEL_KEY[g.band]), color: confidenceBandColor(g.band) }))}
      accentColor={confidenceBandColor('VERY_HIGH')}
    >
      <div className="flex flex-col items-center gap-4">
        <NewsHeaderBlock article={article} alertCreatedAt={alertCreatedAt} />
        <p className="font-data text-[10px] uppercase tracking-widest text-muted">
          Confidence Threshold: {CONFIDENCE_THRESHOLD}%
        </p>
        <div className="flex w-full gap-4">
          <div className="flex flex-1 flex-col gap-6">
            {groups.map((group) => (
              <LevelBand key={group.band} label={t(BAND_LABEL_KEY[group.band])}>
                {group.companies.map((c) => (
                  <CompanyNode
                    key={c.company_id}
                    name={c.name}
                    ticker={c.ticker}
                    direction={c.direction}
                    magnitudeLow={c.magnitude_low}
                    magnitudeHigh={c.magnitude_high}
                    confidenceScore={c.confidence_score}
                    inMyHoldings={c.in_my_holdings}
                    onClick={() => toggle(c.company_id)}
                    selected={selectedId === c.company_id}
                  />
                ))}
              </LevelBand>
            ))}
          </div>
          {/* Right-side confidence axis (reference: docs/charts-reference.png)
              -- the same BAND_ORDER top-to-bottom, always all 4 real bands
              regardless of which ones this alert's companies actually fall
              into, so the scale itself never looks sparse or incomplete. */}
          <div aria-hidden="true" className="hidden w-28 shrink-0 flex-col justify-between gap-2 sm:flex">
            {BAND_ORDER.map((band) => (
              <div key={band} className="flex items-center gap-1.5">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: confidenceBandColor(band) }} />
                <span className="font-data text-[10px] uppercase tracking-widest text-muted">{t(BAND_LABEL_KEY[band])}</span>
              </div>
            ))}
          </div>
        </div>
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
