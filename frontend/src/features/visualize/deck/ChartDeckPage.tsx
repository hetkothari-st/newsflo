import { useEffect, useRef, useState, type JSX } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getAlert, type Alert } from '../../../lib/api';
import { useAuth } from '../../../lib/auth';
import { useLanguage } from '../../../lib/language';
import { useTheme } from '../../../lib/theme';
import { buildGraph } from '../graph/model';
import { availableChartNumbers } from './deckAvailability';
import DeckImpactTree from './DeckImpactTree';
import DeckRipple from './DeckRipple';
import DeckSupplyChain from './DeckSupplyChain';
import DeckLevelTree from './DeckLevelTree';
import DeckConfidenceList from './DeckConfidenceList';
import DeckSplit from './DeckSplit';
import DeckTimeline from './DeckTimeline';
import DeckSectors from './DeckSectors';
import DeckEconomicChain from './DeckEconomicChain';
import DeckKnowledge from './DeckKnowledge';
import './deck.css';

// The charts deck screen, built to the approved chart-1 prototype's shell:
// a compact header (back / kicker + headline / theme toggle), a numbered
// mono rail, a horizontally-swipeable chart area, and a quiet foot hint.
// Chart order matches the two chart-spec docs' ordering; charts with no
// data for this alert are hidden entirely (deckAvailability.ts) and the
// survivors renumber sequentially, so the rail always reads 01..0N.

export default function ChartDeckPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { token } = useAuth();
  const { language } = useLanguage();
  const { toggleTheme } = useTheme();
  const [alert, setAlert] = useState<Alert | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const stripRef = useRef<HTMLDivElement>(null);
  const railRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!id) return;
    let active = true;
    getAlert(Number(id), token, language)
      .then((data) => {
        if (active) setAlert(data);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'Failed to load alert.');
      });
    return () => {
      active = false;
    };
  }, [id, token, language]);

  const handleScroll = () => {
    const strip = stripRef.current;
    if (!strip || strip.clientWidth === 0) return;
    const index = Math.round(strip.scrollLeft / strip.clientWidth);
    if (index >= 0 && index !== activeIndex) setActiveIndex(index);
  };

  const scrollToChart = (index: number) => {
    const strip = stripRef.current;
    if (!strip) return;
    strip.scrollTo({ left: index * strip.clientWidth, behavior: 'smooth' });
    setActiveIndex(index);
  };

  useEffect(() => {
    const rail = railRef.current;
    const active = rail?.children[activeIndex] as HTMLElement | undefined;
    active?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  }, [activeIndex]);

  if (error) return <p className="deck-pagestatus deck-pagestatus-error">{error}</p>;
  if (!alert) return <p className="deck-pagestatus">Loading…</p>;

  const graph = buildGraph(alert);
  const treeProps = {
    companies: alert.companies,
    article: alert.article,
    alertCreatedAt: alert.created_at,
    eventType: alert.event_type,
  };
  const graphProps = { graph, companies: alert.companies, eventType: alert.event_type };

  // Keyed by CANONICAL chart number (availability speaks that language);
  // each builder receives the SEQUENTIAL display number, so hidden charts
  // never leave a gap in the numbering the user sees (rail reads 01..0N).
  const slideByCanonical: Record<number, (displayNumber: number) => JSX.Element> = {
    1: (dn) => <DeckImpactTree key="c1" {...treeProps} displayNumber={dn} />,
    2: (dn) => <DeckRipple key="c2" {...graphProps} displayNumber={dn} />,
    3: (dn) => <DeckSupplyChain key="c3" {...graphProps} displayNumber={dn} />,
    4: (dn) => <DeckLevelTree key="c4" {...treeProps} displayNumber={dn} />,
    5: (dn) => <DeckConfidenceList key="c5" {...treeProps} displayNumber={dn} />,
    6: (dn) => <DeckSplit key="c6" {...treeProps} displayNumber={dn} />,
    7: (dn) => <DeckTimeline key="c7" {...treeProps} displayNumber={dn} />,
    8: (dn) => <DeckSectors key="c8" {...treeProps} displayNumber={dn} />,
    9: (dn) => <DeckEconomicChain key="c9" graph={graph} companies={alert.companies} displayNumber={dn} />,
    10: (dn) => <DeckKnowledge key="c10" {...graphProps} displayNumber={dn} />,
  };
  const visibleNumbers = availableChartNumbers({ companies: alert.companies, graph });
  const slides = visibleNumbers.map((canonical, i) => ({
    number: i + 1,
    element: slideByCanonical[canonical](i + 1),
  }));

  return (
    <div className="deck-page">
      <header className="deck-dhead">
        <button type="button" className="deck-backbtn" onClick={() => navigate('/')}>
          ← Feed
        </button>
        <div className="deck-dhead-mid">
          <div className="deck-dhead-kicker">Impact charts</div>
          <h1 className="deck-dhead-headline">{alert.article.title}</h1>
        </div>
        <button type="button" className="deck-themebtn" aria-label="Toggle theme" onClick={toggleTheme}>
          ◐
        </button>
      </header>
      {slides.length === 0 ? (
        <p className="deck-pagestatus">No chart data for this alert.</p>
      ) : (
        <>
          <div className="deck-rail" ref={railRef} role="tablist" aria-label="Charts">
            {slides.map((slide, i) => (
              <button
                key={slide.number}
                type="button"
                role="tab"
                aria-selected={activeIndex === i}
                className={activeIndex === i ? 'on' : undefined}
                onClick={() => scrollToChart(i)}
              >
                {String(slide.number).padStart(2, '0')}
              </button>
            ))}
          </div>
          <div className="deck-strip" ref={stripRef} onScroll={handleScroll}>
            {slides.map((slide) => (
              <div key={slide.number} className="deck-slide">
                <div className="deck-slidepad">{slide.element}</div>
              </div>
            ))}
          </div>
          <footer className="deck-foothint">← swipe between charts →</footer>
        </>
      )}
    </div>
  );
}
