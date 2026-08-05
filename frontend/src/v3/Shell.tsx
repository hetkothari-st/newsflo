/* The app shell for the card-feed UI (spec v2 §2, §7): phone frame,
   top bar (brand · cap-tier filter · calendar · language · theme), five
   views behind a bottom nav (Feed / Discover / Directory / Portfolio /
   Review), the swipe hint, and the shared bottom-sheet host. Ported from
   the approved prototype (newsflo_full_frontend.html), plus the restored
   calendar + translation mechanisms. */
import { useState } from 'react';
import './v3.css';
import type { CapTier, LayerRow } from './api';
import CalendarSheet from './CalendarSheet';
import DiscoverView from './DiscoverView';
import DirectoryView from './DirectoryView';
import FeedView from './FeedView';
import PortfolioView from './PortfolioView';
import ReviewView from './ReviewView';
import { SheetHost, type SheetRequest } from './Sheets';
import LanguagePicker from '../components/LanguagePicker';
import TranslationProgressBanner from '../components/TranslationProgressBanner';
import { useLanguage } from '../lib/language';
import { useTheme } from '../lib/theme';

type View = 'feed' | 'disc' | 'dir' | 'pf' | 'car';

const CAP_FILTERS: Array<{ cap: CapTier | 'ALL'; label: string; title: string }> = [
  { cap: 'ALL', label: 'All', title: 'All companies' },
  { cap: 'LARGE', label: 'L', title: 'Large cap (top 100 by market cap)' },
  { cap: 'MID', label: 'M', title: 'Mid cap (rank 101–250)' },
  { cap: 'SMALL', label: 'S', title: 'Small cap (rank 251–500)' },
  { cap: 'MICRO', label: 'µ', title: 'Micro cap (rank 501+)' },
];

export default function Shell() {
  const { toggleTheme } = useTheme();
  const { t } = useLanguage();
  const [view, setView] = useState<View>('feed');
  const [capFilter, setCapFilter] = useState<CapTier | 'ALL'>('ALL');
  const [sheet, setSheet] = useState<SheetRequest | null>(null);
  const [calendarOpen, setCalendarOpen] = useState(false);
  // null = today; a YYYY-MM-DD string reopens that IST day's feed (the
  // restored calendar mechanism).
  const [feedDate, setFeedDate] = useState<string | null>(null);
  const [hintDismissed, setHintDismissed] = useState(false);

  const navItems: Array<{ view: View; icon: string; label: string }> = [
    { view: 'feed', icon: '▤', label: t('nav.feed') },
    { view: 'disc', icon: '◈', label: t('v3.navDiscover') },
    { view: 'dir', icon: '≣', label: t('v3.navDirectory') },
    { view: 'pf', icon: '◉', label: t('v3.navPortfolio') },
    { view: 'car', icon: '↺', label: t('v3.navReview') },
  ];

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
        fundamentals: row.fundamentals,
        businessDesc: row.business_desc,
        businessDescSourceUrl: row.business_desc_source_url,
        logoUrl: row.logo_url,
      },
    });
  };

  return (
    <div className="nf3">
      <div className="phone">
        <TranslationProgressBanner />
        <div className="topbar">
          <div className="brand">
            news<span>flo</span>
          </div>
          <div className="tr">
            <div className="capf">
              {CAP_FILTERS.map(({ cap, label, title }) => (
                <button
                  key={cap}
                  className={capFilter === cap ? 'on' : ''}
                  onClick={() => setCapFilter(cap)}
                  aria-label={`Cap filter ${cap}`}
                  title={title}
                >
                  {label}
                </button>
              ))}
            </div>
            <button
              className="theme-btn"
              onClick={() => setCalendarOpen(true)}
              aria-label="Calendar"
              title="News by date"
              data-testid="calendar-button"
            >
              {/* Calendar glyph (frame + binding rings + date grid) -- the
                  old ▦ box read as a generic grid. currentColor so it
                  follows the button ink in both themes. */}
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" focusable="false">
                <rect
                  x="1"
                  y="2.5"
                  width="12"
                  height="10.5"
                  rx="1.5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.2"
                />
                <line x1="1" y1="5.8" x2="13" y2="5.8" stroke="currentColor" strokeWidth="1.2" />
                <line x1="4.2" y1="0.8" x2="4.2" y2="3.4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                <line x1="9.8" y1="0.8" x2="9.8" y2="3.4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                <rect x="3.4" y="7.6" width="1.8" height="1.8" rx="0.4" fill="currentColor" />
                <rect x="6.1" y="7.6" width="1.8" height="1.8" rx="0.4" fill="currentColor" />
                <rect x="8.8" y="7.6" width="1.8" height="1.8" rx="0.4" fill="currentColor" />
                <rect x="3.4" y="10.2" width="1.8" height="1.8" rx="0.4" fill="currentColor" />
                <rect x="6.1" y="10.2" width="1.8" height="1.8" rx="0.4" fill="currentColor" />
              </svg>
            </button>
            <span className="langpick">
              <LanguagePicker />
            </span>
            <button className="theme-btn" onClick={toggleTheme} aria-label="Toggle theme">
              ◐
            </button>
          </div>
        </div>

        {feedDate !== null && view === 'feed' && (
          <div className="datebar">
            <span>{t('v3.viewingDate', { date: feedDate })}</span>
            <button onClick={() => setFeedDate(null)}>{t('v3.backToToday')}</button>
          </div>
        )}

        <FeedView
          active={view === 'feed'}
          capFilter={capFilter}
          date={feedDate}
          onOpenDeepDive={openDeepDive}
          onOpenInfo={openInfo}
          onAnyFlip={() => setHintDismissed(true)}
        />
        <DiscoverView active={view === 'disc'} onOpenDeepDive={openDeepDive} />
        <DirectoryView active={view === 'dir'} onOpenDeepDive={(ticker) => openDeepDive(ticker)} />
        <PortfolioView active={view === 'pf'} onOpenDeepDive={openDeepDive} />
        <ReviewView active={view === 'car'} />

        {view === 'feed' && !hintDismissed && <div className="hint">{t('v3.hint')}</div>}

        <div className="nav">
          {navItems.map((item) => (
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

        {/* Calendar overlay -- same scrim+sheet pattern as SheetHost. */}
        <div
          className={`scrim ${calendarOpen ? 'on' : ''}`}
          onClick={() => setCalendarOpen(false)}
          data-testid="calendar-scrim"
        />
        <div className={`sheet ${calendarOpen ? 'on' : ''}`}>
          <div className="grab" />
          {calendarOpen && (
            <CalendarSheet
              onSelectDate={(date) => {
                setFeedDate(date);
                setCalendarOpen(false);
                setView('feed');
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
