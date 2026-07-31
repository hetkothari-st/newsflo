import type { AlertArticle, AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { confidenceColor } from '../colors';
import { useCompanySelection } from '../charts/useCompanySelection';
import DeckChartFrame from './DeckChartFrame';
import './deck.css';

// Chart 5 -- Confidence Tree (Doc-1 §4). Deliberately NOT a branching tree:
// a ranked list grouped by confidence band, sorted desc within each. This
// is the ONLY chart where confidence_score appears, and it appears as its
// own labelled element (fill bar + number) -- never beside a direction
// arrow, which is the exact bug (§2) that made prior charts read wrong.
const BANDS = [
  { key: 'high', label: 'High', min: 70 },
  { key: 'medium', label: 'Medium', min: 50 },
  { key: 'low', label: 'Low', min: 0 },
] as const;

const THRESHOLD = 70;

function bandOf(score: number) {
  return BANDS.find((b) => score >= b.min) ?? BANDS[BANDS.length - 1];
}

function ConfidenceRow({
  company,
  onClick,
  selected,
}: {
  company: AlertCompany;
  onClick: () => void;
  selected: boolean;
}) {
  const score = company.confidence_score;
  return (
    <button type="button" onClick={onClick} aria-pressed={selected} className="deck-confrow">
      <span className="deck-confticker">{company.ticker}</span>
      <span className="deck-conftrack" aria-hidden="true">
        <span className="deck-conffill" style={{ width: `${Math.max(0, Math.min(100, score))}%`, background: confidenceColor(score) }} />
        <span className="deck-confthreshold" style={{ left: `${THRESHOLD}%` }} />
      </span>
      <span className="deck-confscore">{score}</span>
      <span className="deck-confband">{bandOf(score).label}</span>
    </button>
  );
}

export default function DeckConfidenceList({
  companies,
  article: _article,
  alertCreatedAt: _alertCreatedAt,
  eventType,
  displayNumber = 5,
}: {
  companies: AlertCompany[];
  article: AlertArticle;
  alertCreatedAt: string;
  eventType?: string | null;
  displayNumber?: number;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);

  const groups = BANDS.map((band) => ({
    band,
    companies: companies
      .filter((c) => bandOf(c.confidence_score).key === band.key)
      .sort((a, b) => b.confidence_score - a.confidence_score),
  })).filter((g) => g.companies.length > 0);

  return (
    <DeckChartFrame
      number={displayNumber}
      title="Confidence Tree"
      description={`How directly evidenced each call is. The marker on every bar is the ${THRESHOLD}% high-confidence threshold.`}
    >
      {groups.map((group) => (
        <div key={group.band.key} className="deck-confgroup">
          <span className="deck-groupheader">
            {group.band.label}
            <span className="deck-groupsub">
              {group.band.min > 0 ? ` · ≥${group.band.min}` : ' · <50'} · {group.companies.length}
            </span>
          </span>
          {group.companies.map((c) => (
            <ConfidenceRow key={c.company_id} company={c} onClick={() => toggle(c.company_id)} selected={selectedId === c.company_id} />
          ))}
        </div>
      ))}
      {selected && <ReasoningPanel company={selected} eventType={eventType} />}
    </DeckChartFrame>
  );
}
