import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getAlert, type Alert } from '../../../lib/api';
import { useAuth } from '../../../lib/auth';
import { useLanguage } from '../../../lib/language';
import { useTheme } from '../../../lib/theme';
import { buildGraph } from '../graph/model';
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
// Chart order matches the two chart-spec docs' numbering 1-10.
const CHART_COUNT = 10;

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
    if (index >= 0 && index < CHART_COUNT && index !== activeIndex) setActiveIndex(index);
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

  const slides = [
    <DeckImpactTree key="c1" {...treeProps} />,
    <DeckRipple key="c2" {...graphProps} />,
    <DeckSupplyChain key="c3" {...graphProps} />,
    <DeckLevelTree key="c4" {...treeProps} />,
    <DeckConfidenceList key="c5" {...treeProps} />,
    <DeckSplit key="c6" {...treeProps} />,
    <DeckTimeline key="c7" {...treeProps} />,
    <DeckSectors key="c8" {...treeProps} />,
    <DeckEconomicChain key="c9" graph={graph} companies={alert.companies} />,
    <DeckKnowledge key="c10" {...graphProps} />,
  ];

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
      <div className="deck-rail" ref={railRef} role="tablist" aria-label="Charts">
        {Array.from({ length: CHART_COUNT }, (_, i) => (
          <button
            key={i}
            type="button"
            role="tab"
            aria-selected={activeIndex === i}
            className={activeIndex === i ? 'on' : undefined}
            onClick={() => scrollToChart(i)}
          >
            {String(i + 1).padStart(2, '0')}
          </button>
        ))}
      </div>
      <div className="deck-strip" ref={stripRef} onScroll={handleScroll}>
        {slides.map((slide, i) => (
          <div key={i} className="deck-slide">
            <div className="deck-slidepad">{slide}</div>
          </div>
        ))}
      </div>
      <footer className="deck-foothint">← swipe between charts →</footer>
    </div>
  );
}
