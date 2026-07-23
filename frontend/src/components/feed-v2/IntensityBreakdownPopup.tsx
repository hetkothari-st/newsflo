import { intensityBandColorClass } from '../../lib/feedV2Format';
import type { Intensity } from '../../lib/feedV2Api';

interface IntensityBreakdownPopupProps {
  intensity: Intensity;
}

// Verbatim per docs/NEWS_IMPACT_APP_SPEC.md §4.2/§7 -- never reword. This is
// a compliance control (intensity is a news-impact metric, never a rating),
// not a style choice.
const DISCLAIMER =
  "Intensity measures how hard the news hit this stock — not whether it's a good investment.";

export default function IntensityBreakdownPopup({ intensity }: IntensityBreakdownPopupProps) {
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg bg-surface p-5">
        <div className="flex items-baseline gap-3">
          <span className="font-data text-4xl font-medium text-ink">{intensity.score}</span>
          <span className="font-sans text-sm text-muted">{intensity.band}</span>
        </div>
      </div>

      <div className="rounded-lg bg-surface p-5">
        <div className="flex flex-col gap-3">
          {intensity.components.map((component) => {
            // contribution = normalized_subscore * weight (see
            // app/market/intensity.py::compute_intensity) -- recover the
            // component's own 0-100 sub-score for the mini bar's fill.
            const subScore = component.weight > 0 ? component.contribution / component.weight : 0;
            return (
              <div key={component.label}>
                <div className="font-sans text-sm text-ink">
                  <span className="capitalize">{component.label}</span>
                  {' — '}
                  <span className="font-data">{component.raw.toFixed(1)}</span>
                  <span className="font-data">{` ×${component.weight.toFixed(2)}`}</span>
                </div>
                <div className="mt-1 h-1 w-full rounded-sm bg-elevated">
                  <div
                    className={`h-full rounded-sm ${intensityBandColorClass(intensity.band)}`}
                    style={{ width: `${subScore}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Fundamental note (advisory tier only) deliberately omitted -- no
          FundamentalEstimate data model exists yet (out of scope for this
          build). A future advisory-tier phase adds a fundamentalNote prop
          and renders it here, between the components and the disclaimer. */}

      <div className="rounded-lg bg-surface p-5">
        <p className="font-sans text-xs text-muted">{DISCLAIMER}</p>
      </div>
    </div>
  );
}
