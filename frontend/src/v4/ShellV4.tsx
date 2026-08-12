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
import PulseLiveV4 from './PulseLiveV4';
import { DirectoryV4, DiscoverV4, PortfolioV4, ReviewV4 } from './SectionsV4';

type View = 'feed' | 'pulse' | 'disc' | 'dir' | 'pf' | 'car' | 'arch';

const NAV_ITEMS: Array<{ view: View; label: string }> = [
  { view: 'feed', label: 'Feed' },
  { view: 'pulse', label: 'Pulse' },
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
  // Mini wordmark shown once the big masthead scrolls away. Opacity and
  // transform ONLY (its slot is always in layout) -- scroll must never
  // change layout (the old height-animating header glitched).
  const [condensed, setCondensed] = useState(false);
  const condensedRef = useRef(false);
  // Broadsheet dark mode: a straight paper<->ink inversion (user
  // decision), persisted separately from the v3 shell's theme.
  const [dark, setDark] = useState(() => localStorage.getItem('newsflo.v4.theme') === 'dark');
  const toggleDark = () => {
    setDark((prev) => {
      localStorage.setItem('newsflo.v4.theme', prev ? 'light' : 'dark');
      return !prev;
    });
  };
  const [edition, setEdition] = useState<{ count: number; date: string | null } | null>(null);
  // Pulse-wire item count for the ticker while the Pulse tab is active;
  // null until the wire has loaded.
  const [pulseCount, setPulseCount] = useState<number | null>(null);
  const [bandOpen, setBandOpen] = useState(false);
  const [deepDive, setDeepDive] = useState<{ ticker: string; alertId?: number } | null>(null);
  // The (i) glance popup -- separate from the deep dive: glance and stay.
  const [info, setInfo] = useState<InfoV4Data | null>(null);
  // null = today's edition; set from the archive to reopen a back issue.
  const [feedDate, setFeedDate] = useState<string | null>(null);
  // null = latest pulse day; set from the archive's pulse-wire list.
  const [pulseDate, setPulseDate] = useState<string | null>(null);
  // Returning from the charts page: /v4?ripple=<id> reopens that story's
  // ripple section directly. Read once at mount.
  const [initialRipple, setInitialRipple] = useState<number | null>(() => {
    // Pure read only -- StrictMode double-invokes this initializer, so
    // the URL mutation lives in the mount effect below.
    const raw = new URLSearchParams(window.location.search).get('ripple');
    if (raw === null) return null;
    const parsed = Number(raw);
    return Number.isNaN(parsed) ? null : parsed;
  });
  // Consume the param: strip it from the URL so a refresh doesn't
  // reopen the ripple. Idempotent, safe under StrictMode's double run.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('ripple') === null) return;
    params.delete('ripple');
    const query = params.toString();
    window.history.replaceState(
      null,
      '',
      window.location.pathname + (query ? `?${query}` : ''),
    );
  }, []);
  // Leaving the feed spends the one-shot: coming back from the archive
  // (which remounts FeedV4) must not reopen the ripple.
  useEffect(() => {
    if (view !== 'feed' && initialRipple !== null) setInitialRipple(null);
  }, [view, initialRipple]);
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
  const feedLabel =
    edition === null
      ? 'MEASURING THE TAPE'
      : edition.date !== null
        ? `LATEST EDITION — ${IST_DATE.format(new Date(`${edition.date}T12:00:00`)).toUpperCase()}`
        : `${edition.count} MEASURED ${edition.count === 1 ? 'STORY' : 'STORIES'}`;
  // On the Pulse tab the same ticker slot counts the raw wire instead --
  // pulse items are unmeasured by design, so "measured stories" would lie.
  const editionLabel =
    view === 'pulse'
      ? pulseCount === null
        ? 'READING THE WIRE'
        : `${pulseCount} WIRE ${pulseCount === 1 ? 'STORY' : 'STORIES'}`
      : feedLabel;

  return (
    // Inshorts-style paging on the feed: the shell is the scroll container
    // and snaps per story card. Snapping is dropped while a ripple band is
    // open (mandatory snap fights scrolling through a tall band) and on
    // every non-feed section.
    <div
      className={`nf4 ${(view === 'feed' || view === 'pulse') && !bandOpen ? 'snap' : ''} ${condensed ? 'cond' : ''} ${dark ? 'dark' : ''}`}
      style={{ '--barh': `${barHeight}px`, '--stackh': `${stackHeight}px` } as React.CSSProperties}
      onScroll={(event) => {
        const el = event.currentTarget;
        // Mini-wordmark toggle (opacity/transform only; hysteresis so a
        // boundary position can't flap). Appears only once the BIG
        // masthead has fully scrolled out from under the sticky bar --
        // a fixed low threshold showed both titles at once.
        const bigGone = stackHeight - barHeight;
        const next = condensedRef.current
          ? el.scrollTop > Math.max(8, bigGone - 40)
          : el.scrollTop >= bigGone;
        if (next !== condensedRef.current) {
          condensedRef.current = next;
          setCondensed(next);
        }
        if (view !== 'feed' || bandOpen) return;
        if (settleTimer.current !== null) window.clearTimeout(settleTimer.current);
        const scheduledAt = el.scrollTop;
        settleTimer.current = window.setTimeout(() => {
          const top = el.scrollTop;
          // Only rescue a TRULY settled rest in the dead zone -- if the
          // position moved since scheduling, a snap animation is still
          // running and must not be fought.
          if (Math.abs(top - scheduledAt) < 2 && top > 4 && top < el.clientHeight * 0.75) {
            el.scrollTo({ top: 0, behavior: 'smooth' });
          }
        }, 220);
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
        {/* Fixed-height slot; the wordmark inside scales/fades in as the
            big masthead scrolls away -- the shrink animation without a
            single pixel of layout movement. */}
        <div className="minirow" aria-hidden="true">
          <span className="minimast">Newsflo</span>
        </div>
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
          <button className="themebtn" onClick={toggleDark} aria-label="Toggle theme" title="Light / dark">
            ◐
          </button>
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
          initialOpenId={initialRipple}
          onEdition={setEdition}
          onOpenDeepDive={openDeepDive}
          onOpenInfo={setInfo}
          onBandOpenChange={setBandOpen}
        />
      )}
      {view === 'pulse' && (
        <PulseLiveV4
          date={pulseDate}
          onCount={setPulseCount}
          onBackToLatest={() => setPulseDate(null)}
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
          onPickPulse={(date) => {
            setPulseDate(date);
            setView('pulse');
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
