/* The v4 charts page, built from scratch (user decision -- the older
   deck module is not used): a horizontally snapping strip of charts in
   the broadsheet paper/ink theme, driven entirely by the story's real
   detail payload. Charts without honest data are absent (hide-no-data
   rule). Gestures follow the app convention: drag left = next chart,
   drag right = previous, drag right on the FIRST chart = back to the
   story's ripple section. */
import { useEffect, useRef, useState, type JSX } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getAlertDetail, type AlertDetail } from '../../v3/api';
import { useAuth } from '../../lib/auth';
import InfoV4, { type InfoV4Data } from '../InfoV4';
import { availableCharts, flattenRows } from './chartsData';
import {
  CEconomicChain,
  ChartFrame,
  CImpactTree,
  CIntensity,
  CKnowledge,
  CLevels,
  CRipple,
  CSectors,
  CSplit,
  CTimeline,
} from './chartComponents';
import '../v4.css';
import './charts.css';

export default function ChartsV4Page() {
  const { id } = useParams<{ id: string }>();
  const alertId = Number(id);
  const navigate = useNavigate();
  const { token } = useAuth();
  const [detail, setDetail] = useState<AlertDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const stripRef = useRef<HTMLDivElement>(null);
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  const dark = localStorage.getItem('newsflo.v4.theme') === 'dark';

  useEffect(() => {
    let cancelled = false;
    getAlertDetail(alertId, token, 'en')
      .then((result) => {
        if (!cancelled) setDetail(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [alertId, token]);

  const backToRipple = () => navigate(`/v4?ripple=${alertId}`);

  // The (i) glance popup, opened by tapping any company node/row in any
  // chart. One delegated handler: every company element in the charts
  // carries data-ticker; the row's own detail-payload fields feed the
  // same InfoV4 the ripple section uses.
  const [info, setInfo] = useState<InfoV4Data | null>(null);
  const handleStripClick = (event: React.MouseEvent) => {
    if (detail === null) return;
    const hit = (event.target as Element).closest('[data-ticker]');
    if (hit === null) return;
    const ticker = hit.getAttribute('data-ticker');
    const row = flattenRows(detail).find((r) => r.ticker === ticker);
    if (!row) return;
    setInfo({
      name: row.name,
      ticker: row.ticker,
      sector: row.sector,
      logoUrl: row.logo_url,
      fundamentals: row.fundamentals,
      businessDesc: row.business_desc,
      businessDescSourceUrl: row.business_desc_source_url,
      volatilityRange: row.volatility_range,
    });
  };

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

  const charts = detail === null ? [] : availableCharts(detail);
  const renderers: Record<string, (d: AlertDetail) => JSX.Element> = {
    impactTree: (d) => <CImpactTree detail={d} />,
    ripple: (d) => <CRipple detail={d} />,
    levels: (d) => <CLevels detail={d} />,
    intensity: (d) => <CIntensity detail={d} />,
    split: (d) => <CSplit detail={d} />,
    sectors: (d) => <CSectors detail={d} />,
    timeline: (d) => <CTimeline detail={d} />,
    economicChain: (d) => <CEconomicChain detail={d} />,
    knowledge: (d) => <CKnowledge detail={d} />,
  };

  return (
    <div className={`nf4 chartspage ${dark ? 'dark' : ''}`}>
      <header className="cpage-head">
        <button className="cpage-back" onClick={backToRipple}>
          ← The Ripple
        </button>
        <div className="cpage-kicker">Impact charts</div>
      </header>
      {error !== null && <p className="empty4">{error}</p>}
      {detail === null && error === null && (
        <div className="ddloading" aria-busy="true">
          <span className="ddload-rule" />
          <p>Setting the type…</p>
          <span className="ddload-rule" />
        </div>
      )}
      {detail !== null && charts.length === 0 && (
        <p className="empty4">No chart has honest data for this story.</p>
      )}
      {detail !== null && charts.length > 0 && (
        <>
          <div className="cpage-rail" role="tablist" aria-label="Charts">
            {charts.map((meta, i) => (
              <button
                key={meta.kind}
                role="tab"
                aria-selected={activeIndex === i}
                className={activeIndex === i ? 'on' : ''}
                onClick={() => scrollToChart(i)}
              >
                {String(i + 1).padStart(2, '0')}
              </button>
            ))}
          </div>
          <div
            className="cpage-strip"
            ref={stripRef}
            onScroll={handleScroll}
            onClick={handleStripClick}
            onTouchStart={(event) => {
              touchStart.current = { x: event.touches[0].clientX, y: event.touches[0].clientY };
            }}
            onTouchEnd={(event) => {
              if (touchStart.current === null) return;
              const dx = event.changedTouches[0].clientX - touchStart.current.x;
              const dy = event.changedTouches[0].clientY - touchStart.current.y;
              touchStart.current = null;
              // Only the exit gesture is custom -- chart-to-chart paging
              // is the strip's native horizontal snap.
              if (activeIndex === 0 && dx > 55 && Math.abs(dx) > Math.abs(dy) * 1.5) {
                backToRipple();
              }
            }}
          >
            {charts.map((meta, i) => (
              <div className="cpage-slide" key={meta.kind}>
                <ChartFrame number={i + 1} meta={meta} detail={detail}>
                  {renderers[meta.kind](detail)}
                </ChartFrame>
              </div>
            ))}
          </div>
          <footer className="cpage-foot">← swipe between charts · swipe right past 01 for the ripple</footer>
        </>
      )}
      {info !== null && <InfoV4 info={info} onClose={() => setInfo(null)} />}
    </div>
  );
}
