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

// The glance sheet is a quick "who is this company" look for a reader who
// does not know what P/E means: plain-language label, contextualized value,
// and the abbreviation demoted to a small tag for those who do. No P/B (no
// honest one-phrase gloss exists for it) and no consolidated block -- the
// full technical set lives in the deep dive.
const GLANCE_ROWS: Array<{
  key: RatioKey;
  label: string;
  tag: string;
  format: (value: number) => string;
}> = [
  { key: 'pe', label: 'Price vs yearly profit', tag: 'P/E', format: (v) => `${v.toFixed(1)}×` },
  { key: 'opm', label: 'Profit kept from sales', tag: 'OPM', format: (v) => `${v.toFixed(1)}%` },
  { key: 'roe', label: "Return on shareholders' money", tag: 'ROE', format: (v) => `${v.toFixed(1)}%` },
];

// Sourced-fact panel: BSE's official classification path plus whichever
// ratios it actually published, each traceable to a source and an as-of
// date. Replaces the LLM-invented business_desc paragraph (see
// docs/superpowers/specs/2026-08-04-sourced-company-fundamentals-design.md).
// Shared across call sites in two different design systems --
// InsightCard/BusinessPopup (the Tailwind editorial tree) AND v3/Sheets.tsx
// (its own `.nf3`-scoped stylesheet, no Tailwind classes anywhere else in
// that tree) -- so this deliberately never forces a font-family utility:
// classification/ratio/date text inherits whichever ambient body font its
// host already sets (Newsreader serif in InsightCard, system sans in
// BusinessPopup and v3). `border-hairline`/`text-ink`/`text-muted` are safe
// everywhere -- both trees' CSS variables for page/ink/muted/hairline
// resolve to near-identical dark-theme colors (compared directly:
// index.css's --color-page/ink/muted/hairline vs v3.css's --bg/ink/ink2/
// border), and v3 already uses this exact "hairline rule above a trailing
// note" pattern for its own `.disc` block.
//
// Zeros never reach this component: the backend omits BSE's literal "0.00"
// not-published sentinel at the serve layer (app.companies.fundamentals),
// so any value present here is a real published figure (negatives included
// -- loss-making EPS is a fact, not a sentinel).
export default function Fundamentals({
  data,
  variant = 'full',
}: {
  data: FundamentalsData | null | undefined;
  variant?: 'full' | 'glance';
}) {
  if (!data) return null; // no invented filler -- ~645 companies have no classification

  const { classification: c, ratios, consolidated, as_of, source, financials_as_of, financials_source } = data;
  // BSE's four levels frequently repeat verbatim ("Construction ›
  // Construction" for L&T) -- adjacent duplicates carry no information and
  // read as a rendering bug, so collapse them. Non-adjacent repeats are
  // kept: they would indicate genuinely different levels sharing a name.
  const path = [c.sector, c.industry, c.group, c.sub_group]
    .filter((value): value is string => Boolean(value))
    .filter((value, index, all) => index === 0 || value !== all[index - 1]);

  // A filter on `!== undefined`, never a truthiness check -- a real
  // negative value (loss-making EPS) must survive.
  const glanceRows =
    variant === 'glance'
      ? GLANCE_ROWS.map((row) => ({ ...row, value: ratios?.[row.key] })).filter(
          (entry): entry is (typeof GLANCE_ROWS)[number] & { value: number } =>
            entry.value !== undefined,
        )
      : [];
  const shown =
    variant === 'glance'
      ? []
      : RATIO_LABELS.map(([key, label]) => ({ key, label, value: ratios?.[key] })).filter(
          (entry): entry is { key: RatioKey; label: string; value: number } =>
            entry.value !== undefined,
        );
  const shownConsolidated =
    variant === 'glance'
      ? []
      : RATIO_LABELS.map(([key, label]) => ({
          key,
          label,
          value: consolidated?.[key],
        })).filter(
          (entry): entry is { key: RatioKey; label: string; value: number } => entry.value !== undefined,
        );

  if (
    path.length === 0 && shown.length === 0 &&
    glanceRows.length === 0 && shownConsolidated.length === 0
  ) return null;

  // The trailing date/source note is about whatever is actually shown above
  // it: when ratios (standalone or consolidated) are on screen, that note
  // must describe THEIR provenance (financials_source/financials_as_of),
  // not the classification's -- the two are sourced on their own cadences
  // (backend app.companies.fundamentals keeps them as separate keys for
  // exactly this reason) and P/E and P/B are price-derived, so the ratio
  // date is what keeps a stale figure honest (spec 5.1). Classification-only
  // payloads (no ratios shown) fall back to the classification's own
  // source/as_of, same as before this distinction existed.
  const hasRatios = shown.length > 0 || glanceRows.length > 0 || shownConsolidated.length > 0;
  const noteAsOf = hasRatios && financials_as_of ? financials_as_of : as_of;
  const noteSource = hasRatios && financials_as_of ? financials_source : source;

  return (
    <div data-testid="fundamentals" className="mt-2 border-t border-hairline pt-2">
      {path.length > 0 && <p className="text-xs text-muted">{path.join(' › ')}</p>}
      {glanceRows.length > 0 && (
        <dl className="mt-1.5 flex flex-col gap-1">
          {glanceRows.map(({ key, label, tag, format, value }) => (
            <div key={key} className="flex items-baseline justify-between gap-3 text-[12px]">
              <dt className="text-muted">{label}</dt>
              <dd className="flex items-baseline gap-1.5 whitespace-nowrap">
                <span className="font-data font-semibold text-ink">{format(value)}</span>
                <span className="font-data text-[9px] uppercase tracking-widest text-muted">{tag}</span>
              </dd>
            </div>
          ))}
        </dl>
      )}
      {shown.length > 0 && (
        // Numeric ratios still opt into a monospace treatment -- the one
        // typographic idiom InsightCard (font-data), BusinessPopup
        // (font-data), and v3 (--mono, e.g. .tag/.tkr/.tile .v) already
        // share for tabular/data values.
        <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
          {shown.map(({ key, label, value }) => (
            <div key={key} className="flex items-baseline gap-1 font-data text-[11px]">
              <dt className="uppercase tracking-widest text-muted">{label}</dt>
              <dd className="font-semibold text-ink">{value.toFixed(2)}</dd>
            </div>
          ))}
        </dl>
      )}
      {shownConsolidated.length > 0 && (
        <div className="mt-1">
          <p className="text-[10px] uppercase tracking-widest text-muted">consolidated</p>
          <dl className="mt-0.5 flex flex-wrap gap-x-4 gap-y-1">
            {shownConsolidated.map(({ key, label, value }) => (
              <div key={key} className="flex items-baseline gap-1 font-data text-[11px]">
                <dt className="uppercase tracking-widest text-muted">{label}</dt>
                <dd className="font-semibold text-ink">{value.toFixed(2)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      {/* The date is load-bearing, not decoration: P/E and P/B are
          price-derived and this data refreshes monthly (spec 5.1) -- it is
          the only thing that keeps a stale ratio honest. See noteAsOf/
          noteSource above for which provenance this describes. */}
      {noteAsOf && (
        <p className="mt-1 text-[11px] text-muted">
          {noteSource ?? 'source unknown'} · as of {noteAsOf}
        </p>
      )}
    </div>
  );
}
