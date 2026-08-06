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
  // Condensed header once the reader scrolls past the homepage: the
  // masthead shrinks to a compact bar that stays pinned over every card.
  // Hysteresis (condense past 80px, expand only under 8px) so the toggle
  // can't oscillate at a boundary.
  const [condensed, setCondensed] = useState(false);
  const condensedRef = useRef(false);
  const [edition, setEdition] = useState<{ count: number; date: string | null } | null>(null);
  const [bandOpen, setBandOpen] = useState(false);
  const [deepDive, setDeepDive] = useState<{ ticker: string; alertId?: number } | null>(null);
  // The (i) glance popup -- separate from the deep dive: glance and stay.
  const [info, setInfo] = useState<InfoV4Data | null>(null);
  // null = today's edition; set from the archive to reopen a back issue.
  const [feedDate, setFeedDate] = useState<string | null>(null);
  // Two FROZEN header measurements instead of one live value: the full
  // (homepage) height sizes the first card, the condensed height sizes
  // every later card and the snap padding. Each updates only while the
  // header is in that state, so a condense/expand toggle never re-sizes
  // the layout it is scrolling over -- the live-value version fed its
  // own scroll position back into itself and oscillated (reported on
  // phone: header and cards contracting/expanding in a loop).
  const headerRef = useRef<HTMLElement | null>(null);
  const [headFull, setHeadFull] = useState(220);
  const [headCond, setHeadCond] = useState(72);
  useEffect(() => {
    const el = headerRef.current;
    if (!el) return;
    const measure = () => {
      if (condensedRef.current) setHeadCond(el.offsetHeight);
      else setHeadFull(el.offsetHeight);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(el);
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
      className={`nf4 ${view === 'feed' && !bandOpen ? 'snap' : ''} ${condensed ? 'cond' : ''}`}
      style={{ '--headfull': `${headFull}px`, '--headcond': `${headCond}px` } as React.CSSProperties}
      onScroll={(event) => {
        const top = event.currentTarget.scrollTop;
        const next = condensedRef.current ? top > 8 : top > 80;
        if (next !== condensedRef.current) {
          condensedRef.current = next;
          setCondensed(next);
        }
      }}
    >
      {/* Fixed page-top snap point -- the sticky header can't carry one
          (its snap position would follow the scroll). */}
      <div className="snaptop" aria-hidden="true" />
      <header ref={headerRef} className="tophead">
        <div className="ticker">
          <span>{IST_DATE.format(new Date()).toUpperCase()}</span>
          <span>{editionLabel}</span>
          <span>NSE · BSE — EXCESS MOVE VS SECTOR</span>
        </div>

        <div className="masthead">Newsflo</div>

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
