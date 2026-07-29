/* The app shell for the card-feed UI (spec v2 §2, §7): phone frame,
   top bar (brand · cap-tier filter · theme toggle), five views behind a
   bottom nav (Feed / Discover / Directory / Portfolio / Review), the
   swipe hint, and the shared bottom-sheet host. Ported from the approved
   prototype (newsflo_full_frontend.html). */
import { useState } from 'react';
import './v3.css';
import type { CapTier, LayerRow } from './api';
import DiscoverView from './DiscoverView';
import DirectoryView from './DirectoryView';
import FeedView from './FeedView';
import PortfolioView from './PortfolioView';
import ReviewView from './ReviewView';
import { SheetHost, type SheetRequest } from './Sheets';
import { useTheme } from '../lib/theme';

type View = 'feed' | 'disc' | 'dir' | 'pf' | 'car';

const NAV_ITEMS: Array<{ view: View; icon: string; label: string }> = [
  { view: 'feed', icon: '▤', label: 'Feed' },
  { view: 'disc', icon: '◈', label: 'Discover' },
  { view: 'dir', icon: '≣', label: 'Directory' },
  { view: 'pf', icon: '◉', label: 'Portfolio' },
  { view: 'car', icon: '↺', label: 'Review' },
];

const CAP_FILTERS: Array<{ cap: CapTier | 'ALL'; label: string }> = [
  { cap: 'ALL', label: 'All' },
  { cap: 'LARGE', label: 'L' },
  { cap: 'MID', label: 'M' },
  { cap: 'SMALL', label: 'S' },
  { cap: 'MICRO', label: 'µ' },
];

export default function Shell() {
  const { toggleTheme } = useTheme();
  const [view, setView] = useState<View>('feed');
  const [capFilter, setCapFilter] = useState<CapTier | 'ALL'>('ALL');
  const [sheet, setSheet] = useState<SheetRequest | null>(null);
  const [hintDismissed, setHintDismissed] = useState(false);

  const openDeepDive = (ticker: string, alertId?: number) => {
    setSheet({ kind: 'deepDive', ticker, alertId });
  };

  const openInfo = (row: LayerRow) => {
    setSheet({
      kind: 'info',
      info: {
        name: row.name,
        ticker: row.ticker,
        sector: row.sector,
        businessDesc: row.business_desc,
      },
    });
  };

  return (
    <div className="nf3">
      <div className="phone">
        <div className="topbar">
          <div className="brand">
            news<span>flo</span>
          </div>
          <div className="tr">
            <div className="capf">
              {CAP_FILTERS.map(({ cap, label }) => (
                <button
                  key={cap}
                  className={capFilter === cap ? 'on' : ''}
                  onClick={() => setCapFilter(cap)}
                  aria-label={`Cap filter ${cap}`}
                >
                  {label}
                </button>
              ))}
            </div>
            <button className="theme-btn" onClick={toggleTheme} aria-label="Toggle theme">
              ◐
            </button>
          </div>
        </div>

        <FeedView
          active={view === 'feed'}
          capFilter={capFilter}
          onOpenDeepDive={openDeepDive}
          onOpenInfo={openInfo}
          onAnyFlip={() => setHintDismissed(true)}
        />
        <DiscoverView active={view === 'disc'} onOpenDeepDive={openDeepDive} />
        <DirectoryView active={view === 'dir'} onOpenDeepDive={(ticker) => openDeepDive(ticker)} />
        <PortfolioView active={view === 'pf'} onOpenDeepDive={openDeepDive} />
        <ReviewView active={view === 'car'} />

        {view === 'feed' && !hintDismissed && (
          <div className="hint">Tap card → ripple · scroll → next story</div>
        )}

        <div className="nav">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.view}
              className={view === item.view ? 'on' : ''}
              onClick={() => setView(item.view)}
              aria-label={item.label}
            >
              <span className="ic" aria-hidden="true">
                {item.icon}
              </span>
              {item.label}
            </button>
          ))}
        </div>

        <SheetHost
          request={sheet}
          onClose={() => setSheet(null)}
          onOpenPeer={(ticker, alertId) => openDeepDive(ticker, alertId)}
        />
      </div>
    </div>
  );
}
