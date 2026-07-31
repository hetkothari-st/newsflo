import type { ReactNode } from 'react';
import './deck.css';

export interface DeckLegendItem {
  label: string;
  // A CSS color (theme var or validated hex from colors.ts) for the swatch.
  color: string;
}

// The per-chart header + legend frame from the approved prototype: mono
// accent chart number, plain title, one quiet description line, optional
// swatch legend at the bottom. Austere (Doc-1 §5) -- no card chrome, no
// badge circles; the deck page provides the surrounding surface.
export default function DeckChartFrame({
  number,
  title,
  description,
  legend,
  children,
}: {
  number: number;
  title: string;
  description: string;
  legend?: DeckLegendItem[];
  children: ReactNode;
}) {
  return (
    <section className="deck-chart">
      <div className="deck-chead">
        <span className="deck-cnum">{String(number).padStart(2, '0')}</span>
        <span className="deck-cname">{title}</span>
      </div>
      <p className="deck-cdesc">{description}</p>
      <div className="deck-cbody">{children}</div>
      {legend && legend.length > 0 && (
        <div className="deck-clegend" data-testid="deck-legend">
          {legend.map((item) => (
            <span key={item.label}>
              <span className="deck-sw" style={{ background: item.color }} aria-hidden="true" />
              {item.label}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
