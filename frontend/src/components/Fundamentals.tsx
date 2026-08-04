import type { Fundamentals as FundamentalsData } from '../lib/api';

type RatioKey = keyof NonNullable<FundamentalsData['ratios']>;

const RATIO_LABELS: Array<[RatioKey, string]> = [
  ['pe', 'P/E'],
  ['pb', 'P/B'],
  ['eps', 'EPS'],
  ['ceps', 'CEPS'],
  ['opm', 'OPM %'],
  ['npm', 'NPM %'],
  ['roe', 'ROE %'],
];

// Sourced-fact panel: BSE's official classification path plus whichever
// ratios it actually published, each traceable to a source and an as-of
// date. Replaces the LLM-invented business_desc paragraph (see
// docs/superpowers/specs/2026-08-04-sourced-company-fundamentals-design.md).
// Shared by InsightCard and RippleSection so the two panels cannot drift.
export default function Fundamentals({ data }: { data: FundamentalsData | null | undefined }) {
  if (!data) return null; // no invented filler -- ~645 companies have no classification

  const { classification: c, ratios, as_of, source } = data;
  const path = [c.sector, c.industry, c.group, c.sub_group].filter(
    (value): value is string => Boolean(value),
  );

  // Every ratio the payload actually carries -- a filter on `!== undefined`,
  // never a truthiness check, so a real 0.0 (e.g. NPM) still renders as
  // "0.00" rather than being mistaken for "not reported".
  const shown = RATIO_LABELS.map(([key, label]) => ({ key, label, value: ratios?.[key] })).filter(
    (entry): entry is { key: RatioKey; label: string; value: number } => entry.value !== undefined,
  );

  if (path.length === 0 && shown.length === 0) return null;

  return (
    <div data-testid="fundamentals" className="mt-2 border-t border-hairline pt-2">
      {path.length > 0 && (
        <p className="font-editorial text-xs italic text-muted">{path.join(' › ')}</p>
      )}
      {shown.length > 0 && (
        <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
          {shown.map(({ key, label, value }) => (
            <div key={key} className="flex items-baseline gap-1 font-data text-[11px]">
              <dt className="uppercase tracking-widest text-muted">{label}</dt>
              <dd className="font-semibold text-ink">{value.toFixed(2)}</dd>
            </div>
          ))}
        </dl>
      )}
      {/* The date is load-bearing, not decoration: P/E and P/B are
          price-derived and this data refreshes monthly (spec 5.1) -- it is
          the only thing that keeps a stale ratio honest. */}
      {as_of && (
        <p className="mt-1 font-data text-[10px] uppercase tracking-widest text-muted">
          {source ?? 'source unknown'} · as of {as_of}
        </p>
      )}
    </div>
  );
}
