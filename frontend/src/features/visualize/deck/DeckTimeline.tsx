import type { AlertArticle, AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { useCompanySelection } from '../charts/useCompanySelection';
import { TIME_HORIZON_ORDER, rankByMove } from '../transforms';
import DeckChartFrame from './DeckChartFrame';
import DeckCompanyRow from './DeckCompanyRow';
import './deck.css';

// Chart 7 -- Timeline Tree (Doc-1 §4). A vertical rail with one dot per
// time_horizon bucket in fixed order; only horizons that actually have
// companies render. Dot color is PER-HORIZON, not per-direction -- the rail
// encodes "when", the row glyphs already encode "which way".
//
// Horizon colors reuse four already-validated hexes from colors.ts's
// SECTOR_COLOR palette (see its validation comment) rather than introducing
// new unvalidated colors -- same approach impactLevels.ts took.
const HORIZON_COLOR: Record<string, string> = {
  Immediate: '#E85D4C',
  'Short-Term': '#C97F0E',
  'Medium-Term': '#4A90D9',
  'Long-Term': '#12A08C',
};

const HORIZON_SUB: Record<string, string> = {
  Immediate: 'days',
  'Short-Term': 'weeks',
  'Medium-Term': 'months',
  'Long-Term': 'a year plus',
};

const OTHER_KEY = 'Unspecified';

export default function DeckTimeline({
  companies,
  article: _article,
  alertCreatedAt: _alertCreatedAt,
  eventType,
}: {
  companies: AlertCompany[];
  article: AlertArticle;
  alertCreatedAt: string;
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);

  const known = new Set<string>(TIME_HORIZON_ORDER);
  const buckets = TIME_HORIZON_ORDER.map((horizon) => ({
    key: horizon as string,
    companies: companies.filter((c) => c.time_horizon === horizon),
  }));
  // A row with an unrecognized horizon is shown honestly at the end, never
  // silently dropped (sparse-data rule §6: real rows always render).
  const other = companies.filter((c) => !known.has(c.time_horizon));
  if (other.length > 0) buckets.push({ key: OTHER_KEY, companies: other });
  const visible = buckets.filter((b) => b.companies.length > 0);

  return (
    <DeckChartFrame
      number={7}
      title="Timeline Tree"
      description="When each impact is expected to play out, from days to a year plus."
      legend={visible.map((b) => ({
        label: b.key,
        color: HORIZON_COLOR[b.key] ?? 'rgb(var(--color-muted))',
      }))}
    >
      <div className="deck-timeline">
        {visible.map((bucket) => (
          <div key={bucket.key} className="deck-timeline-step">
            <span
              className="deck-timeline-dot"
              style={{ background: HORIZON_COLOR[bucket.key] ?? 'rgb(var(--color-muted))' }}
              aria-hidden="true"
            />
            <div className="deck-timeline-body">
              <span className="deck-groupheader">
                {bucket.key}
                {HORIZON_SUB[bucket.key] && <span className="deck-groupsub"> · {HORIZON_SUB[bucket.key]}</span>}
                <span className="deck-groupsub"> · {bucket.companies.length}</span>
              </span>
              {rankByMove(bucket.companies).map((c) => (
                <DeckCompanyRow key={c.company_id} company={c} onClick={() => toggle(c.company_id)} selected={selectedId === c.company_id} />
              ))}
            </div>
          </div>
        ))}
      </div>
      {selected && <ReasoningPanel company={selected} eventType={eventType} />}
    </DeckChartFrame>
  );
}
