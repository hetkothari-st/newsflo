/* v4 "Broadsheet" shell -- the Henry-style editorial front page
   (DESIGN.md): top ticker banner, edge-to-edge condensed masthead,
   uppercase nav row with the cap filter (active = larger, never a
   different color). All five sections carry over from the v3 shell --
   Feed (front page), Discover, Directory, Portfolio, Review -- plus the
   deep dive as a full-bleed ink "inside page". English-only while the
   experiment runs. */
import { useEffect, useRef, useState } from 'react';
import './v4.css';
import ArchiveV4 from './ArchiveV4';
import DeepDiveV4 from './DeepDiveV4';
import FeedV4 from './FeedV4';
import InfoV4, { type InfoV4Data } from './InfoV4';
import { DirectoryV4, DiscoverV4, PortfolioV4, ReviewV4 } from './SectionsV4';

type View = 'feed' | 'disc' | 'dir' | 'pf' | 'car' | 'arch';

const NAV_ITEMS: Array<{ view: View; label: string }> = [
  { view: 'feed', label: 'Feed' },
  { view: 'disc', label: 'Discover' },
  { view: 'dir', label: 'Directory' },
  { view: 'pf', label: 'Portfolio' },
  { view: 'car', label: 'Review' },
  { view: 'arch', label: 'Archive' },
];

const IST_DATE = new Intl.DateTimeFormat('en-IN', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  timeZone: 'Asia/Kolkata',
});

export default function ShellV4() {
  const [view, setView] = useState<View>('feed');
  // Scroll settle-assist: iOS sometimes rests between the homepage and
  // card two (half of card one visible) despite mandatory snapping --
  // after the scroll goes idle in that dead zone, finish the trip home.
  const settleTimer = useRef<number | null>(null);
  const [edition, setEdition] = useState<{ count: number; date: string | null } | null>(null);
  const [bandOpen, setBandOpen] = useState(false);
  const [deepDive, setDeepDive] = useState<{ ticker: string; alertId?: number } | null>(null);
  // The (i) glance popup -- separate from the deep dive: glance and stay.
  const [info, setInfo] = useState<InfoV4Data | null>(null);
  // null = today's edition; set from the archive to reopen a back issue.
  const [feedDate, setFeedDate] = useState<string | null>(null);
  // LAYOUT NEVER CHANGES on scroll (the previous height-animating header
  // shifted all content mid-gesture and fought the snap -- reported as
  // glitching between cards 1 and 2). The big masthead + ticker are
  // ordinary content that scrolls away; only a CONSTANT-height compact
  // bar (mini wordmark + nav) is sticky, and "minimize" is purely an
  // opacity fade of the mini wordmark. Two constant measurements: the
  // bar (later cards + snap padding) and the whole top stack (first
  // card).
  const bigheadRef = useRef<HTMLDivElement | null>(null);
  const barRef = useRef<HTMLElement | null>(null);
  const [barHeight, setBarHeight] = useState(56);
  const [stackHeight, setStackHeight] = useState(220);
  useEffect(() => {
    const big = bigheadRef.current;
    const bar = barRef.current;
    if (!big || !bar) return;
    const measure = () => {
      setBarHeight(bar.offsetHeight);
      setStackHeight(big.offsetHeight + bar.offsetHeight);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(big);
    observer.observe(bar);
    measure();
    return () => observer.disconnect();
  }, []);

  const openDeepDive = (ticker: string, alertId?: number) => setDeepDive({ ticker, alertId });

  // edition.date is non-null when today was empty and the feed fell back
  // to the most recent day with stories -- the ticker says so.
  const editionLabel =
    edition === null
      ? 'MEASURING THE TAPE'
      : edition.date !== null
        ? `LATEST EDITION — ${IST_DATE.format(new Date(`${edition.date}T12:00:00`)).toUpperCase()}`
        : `${edition.count} MEASURED ${edition.count === 1 ? 'STORY' : 'STORIES'}`;

  return (
    // Inshorts-style paging on the feed: the shell is the scroll container
    // and snaps per story card. Snapping is dropped while a ripple band is
    // open (mandatory snap fights scrolling through a tall band) and on
    // every non-feed section.
    <div
      className={`nf4 ${view === 'feed' && !bandOpen ? 'snap' : ''}`}
      style={{ '--barh': `${barHeight}px`, '--stackh': `${stackHeight}px` } as React.CSSProperties}
      onScroll={(event) => {
        if (view !== 'feed' || bandOpen) return;
        const el = event.currentTarget;
        if (settleTimer.current !== null) window.clearTimeout(settleTimer.current);
        settleTimer.current = window.setTimeout(() => {
          const top = el.scrollTop;
          if (top > 4 && top < el.clientHeight * 0.8) {
            el.scrollTo({ top: 0, behavior: 'smooth' });
          }
        }, 160);
      }}
    >
      {/* Fixed page-top snap point -- the sticky bar can't carry one
          (its snap position would follow the scroll). */}
      <div className="snaptop" aria-hidden="true" />

      {/* Homepage masthead -- ordinary content, scrolls away naturally. */}
      <div ref={bigheadRef} className="bighead">
        <div className="ticker">
          <span>{IST_DATE.format(new Date()).toUpperCase()}</span>
          <span>{editionLabel}</span>
          <span>NSE · BSE — EXCESS MOVE VS SECTOR</span>
        </div>
        <div className="masthead">Newsflo</div>
      </div>

      {/* Constant-height sticky nav row -- the same centered nav strip
          as before (no mini wordmark; user decision), pinned so it stays
          available over every card. Layout never changes on scroll. */}
      <header ref={barRef} className="topbar">
        <div className="navrow">
          <nav className="navlinks" aria-label="Sections">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.view}
                className={view === item.view ? 'on' : ''}
                onClick={() => setView(item.view)}
                aria-label={item.label}
              >
                {item.label}
              </button>
            ))}
          </nav>
        </div>
        {view === 'feed' && feedDate !== null && (
          <div className="dateline">
            <span>Reading the {feedDate} edition</span>
            <button onClick={() => setFeedDate(null)}>Back to today</button>
          </div>
        )}
      </header>

      {view === 'feed' && (
        <FeedV4
          date={feedDate}
          onEdition={setEdition}
          onOpenDeepDive={openDeepDive}
          onOpenInfo={setInfo}
          onBandOpenChange={setBandOpen}
        />
      )}
      {view === 'disc' && <DiscoverV4 onOpenDeepDive={openDeepDive} />}
      {view === 'dir' && <DirectoryV4 onOpenDeepDive={openDeepDive} />}
      {view === 'pf' && <PortfolioV4 onOpenDeepDive={openDeepDive} />}
      {view === 'car' && <ReviewV4 />}
      {view === 'arch' && (
        <ArchiveV4
          onPick={(date) => {
            setFeedDate(date);
            setView('feed');
          }}
        />
      )}

      {deepDive !== null && (
        <DeepDiveV4
          ticker={deepDive.ticker}
          alertId={deepDive.alertId}
          onOpenPeer={openDeepDive}
          onOpenInfo={setInfo}
          onClose={() => setDeepDive(null)}
        />
      )}
      {info !== null && <InfoV4 info={info} onClose={() => setInfo(null)} />}

      <div className="foot4">
        <span>Newsflo — measured market reactions to the day's news</span>
        <span>Intensity measures how hard the news hit — not whether a stock is good to own</span>
      </div>
    </div>
  );
}
