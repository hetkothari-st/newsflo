import type { AlertCompany } from '../../../lib/api';
import { formatPct } from './deckData';
import './deck.css';

// Compact tappable company row for the list-form charts (7 Timeline, 8
// Sector): ticker + name + the displayed move. The number is the MEASURED
// move only (Doc-1 §2); an unmeasured company shows the direction glyph
// alone -- never magnitude, never confidence.
export default function DeckCompanyRow({
  company,
  onClick,
  selected,
}: {
  company: AlertCompany;
  onClick: () => void;
  selected: boolean;
}) {
  const bearish = company.direction === 'bearish';
  return (
    <button type="button" onClick={onClick} aria-pressed={selected} className="deck-crow">
      <span className="deck-crow-ticker">{company.ticker}</span>
      <span className="deck-crow-name">{company.name}</span>
      {company.in_my_holdings && (
        <span className="deck-crow-held" title="In my holdings" aria-label="In my holdings" />
      )}
      <span className={`deck-crow-move ${bearish ? 'deck-down' : 'deck-up'}`}>
        {bearish ? '▼' : '▲'}
        {company.excess_move_pct != null ? ` ${formatPct(company.excess_move_pct)}` : ''}
      </span>
    </button>
  );
}
