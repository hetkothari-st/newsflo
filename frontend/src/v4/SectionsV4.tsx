/* v4 broadsheet section pages: Discover, Directory, Portfolio, Review.
   Functional parity with the v3 views (same endpoints, same framing
   rules) restyled as ruled editorial columns -- serif entry names,
   uppercase meta lines, hairline rules, no chips except outlined ghost
   tags, active tabs emphasised by scale only. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  getCarReview,
  getDirectory,
  getDiscovery,
  getPortfolioOverlay,
  type CapTier,
  type CarReviewRow,
  type DirectoryCompany,
  type DiscoveryEntry,
  type DiscoveryTab,
} from '../v3/api';
import LogoV4 from './LogoV4';
import { displaySector } from '../v3/directoryFilters';
import { formatMarketCap } from './directoryLiveCaps';
import { useDirectoryLiveCaps } from './useDirectoryLiveCaps';
import { useAuth } from '../lib/auth';

function fmtPct(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

const CAP_OPTIONS: Array<CapTier | 'ALL'> = ['ALL', 'LARGE', 'MID', 'SMALL', 'MICRO'];

/* ---------- DISCOVER ---------- */

const TAB_LABELS: Record<DiscoveryTab, string> = {
  materiality: 'Materiality',
  holdings: 'Near holdings',
  unusual: 'Unusual activity',
};

export function DiscoverV4({ onOpenDeepDive }: { onOpenDeepDive: (ticker: string, alertId?: number) => void }) {
  const { token } = useAuth();
  const [tab, setTab] = useState<DiscoveryTab>('materiality');
  const [entries, setEntries] = useState<DiscoveryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setEntries(null);
    setError(null);
    getDiscovery(tab, token)
      .then((result) => {
        if (!cancelled) setEntries(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [tab, token]);

  const maxMateriality = Math.max(...(entries ?? []).map((e) => e.materiality ?? 0), 0);

  const metricFor = (entry: DiscoveryEntry): { text: string; cls: string } => {
    if (tab === 'unusual')
      return { text: entry.volume_multiple != null ? `${entry.volume_multiple.toFixed(1)}× vol` : '—', cls: '' };
    if (tab === 'holdings' && entry.excess_move_pct == null) return { text: 'linked', cls: '' };
    if (entry.excess_move_pct == null) return { text: '—', cls: '' };
    return { text: fmtPct(entry.excess_move_pct), cls: entry.excess_move_pct < 0 ? 'down' : 'up' };
  };

  return (
    <div className="page4">
      <h1 className="phead">Discover</h1>
      <p className="psub">Smaller names the headlines miss. Ranked by impact, not prominence.</p>
      <div className="texttabs">
        {(Object.keys(TAB_LABELS) as DiscoveryTab[]).map((key) => (
          <button key={key} className={tab === key ? 'on' : ''} onClick={() => setTab(key)}>
            {TAB_LABELS[key]}
          </button>
        ))}
      </div>
      {error !== null && <p className="empty4">{error}</p>}
      {entries !== null && entries.length === 0 && (
        <p className="empty4">
          {tab === 'holdings'
            ? 'Nothing near your holdings today. Sign in and add holdings to see smaller names the same news touches.'
            : 'Nothing to surface yet today.'}
        </p>
      )}
      {entries?.map((entry) => {
        const metric = metricFor(entry);
        const warn =
          entry.low_delivery && entry.delivery_pct != null
            ? 'Low delivery'
            : tab === 'unusual' && entry.thin_trading
              ? 'Thin trading'
              : null;
        return (
          <div
            className="entry4"
            key={`${entry.ticker}-${entry.alert_id}`}
            onClick={() => onOpenDeepDive(entry.ticker, entry.alert_id)}
          >
            <LogoV4 logoUrl={entry.logo_url} ticker={entry.ticker} name={entry.name} />
            <div className="ebody">
            <div className="etop">
              <span className="ename">{entry.name}</span>
              <span className={`emetric ${metric.cls}`}>{metric.text}</span>
            </div>
            <p className="ewhy">{entry.why ?? entry.headline}</p>
            <div className="emeta">
              <span>{entry.ticker}</span>
              {entry.cap_tier !== null && <span>{entry.cap_tier}</span>}
              {entry.liquidity_tier !== null && <span>{entry.liquidity_tier} liquidity</span>}
              {tab === 'holdings' && entry.via_ticker && <span>via {entry.via_ticker}</span>}
              {warn !== null && <span className="warn4">⚠ {warn}</span>}
              {warn === null && entry.materiality != null && maxMateriality > 0 && (
                <span>materiality {Math.round((entry.materiality / maxMateriality) * 100)}</span>
              )}
            </div>
            </div>
          </div>
        );
      })}
      <p className="emeta" style={{ marginTop: 24 }}>
        Framing is factual — "most affected by news", never "best to buy".
      </p>
    </div>
  );
}

/* ---------- DIRECTORY ---------- */

/* Autocomplete matching: prefix beats substring, ties by live rank.
   Pure client-side -- the whole directory is already loaded. */
function searchMatches(
  companies: DirectoryCompany[],
  query: string,
  rankOf: (ticker: string) => number,
): DirectoryCompany[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const scored = companies
    .map((company) => {
      const name = company.name.toLowerCase();
      const ticker = company.ticker.toLowerCase();
      const prefix = name.startsWith(q) || ticker.startsWith(q);
      const anywhere = prefix || name.includes(q) || ticker.includes(q);
      return anywhere ? { company, prefix } : null;
    })
    .filter((entry): entry is { company: DirectoryCompany; prefix: boolean } => entry !== null);
  scored.sort(
    (a, b) =>
      Number(b.prefix) - Number(a.prefix) ||
      rankOf(a.company.ticker) - rankOf(b.company.ticker) ||
      a.company.ticker.localeCompare(b.company.ticker),
  );
  return scored.slice(0, 8).map((entry) => entry.company);
}

export function DirectoryV4({ onOpenDeepDive }: { onOpenDeepDive: (ticker: string) => void }) {
  const { token } = useAuth();
  const [companies, setCompanies] = useState<DirectoryCompany[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [capFilter, setCapFilter] = useState<CapTier | 'ALL'>('ALL');
  const [sectorFilter, setSectorFilter] = useState<string>('ALL');
  // Search: the query filters the ranked list live; the dropdown offers
  // the top matches, and picking one jumps to (and briefly highlights)
  // that company's row in the full ranking.
  const [query, setQuery] = useState('');
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [highlightTicker, setHighlightTicker] = useState<string | null>(null);
  const highlightTimer = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getDirectory(token)
      .then((result) => {
        if (!cancelled) setCompanies(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  // displaySector bifurcates "banking" into Banking vs Finance (non-bank
  // financials) at display level -- same split as the v3 Directory.
  const sectors = useMemo(() => {
    const unique = new Set((companies ?? []).map(displaySector));
    return ['ALL', ...Array.from(unique).sort()];
  }, [companies]);

  // Live market-cap ranking: /directory/live-caps polls every 5s (live
  // tick x shares where available, stored cap otherwise) and the list
  // re-sorts by it -- caps barely move within 5s, so row swaps are rare.
  // Until the first poll lands, rows keep the API's ticker order.
  const liveCaps = useDirectoryLiveCaps();
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = (companies ?? []).filter(
      (company) =>
        (capFilter === 'ALL' || company.cap_tier === capFilter) &&
        (sectorFilter === 'ALL' || displaySector(company) === sectorFilter) &&
        (q === '' ||
          company.name.toLowerCase().includes(q) ||
          company.ticker.toLowerCase().includes(q)),
    );
    if (liveCaps.size === 0) return rows;
    return [...rows].sort(
      (a, b) =>
        (liveCaps.get(a.ticker)?.rank ?? Number.MAX_SAFE_INTEGER) -
          (liveCaps.get(b.ticker)?.rank ?? Number.MAX_SAFE_INTEGER) ||
        a.ticker.localeCompare(b.ticker),
    );
  }, [companies, capFilter, sectorFilter, liveCaps, query]);

  const suggestions = useMemo(
    () =>
      dropdownOpen && query.trim() !== ''
        ? searchMatches(
            companies ?? [],
            query,
            (ticker) => liveCaps.get(ticker)?.rank ?? Number.MAX_SAFE_INTEGER,
          )
        : [],
    [companies, query, dropdownOpen, liveCaps],
  );

  // Jump to a company's row in the full ranking: clear the query, lift
  // any filter that would hide it, then scroll + pulse the row.
  const jumpTo = (company: DirectoryCompany) => {
    setQuery('');
    setDropdownOpen(false);
    if (capFilter !== 'ALL' && company.cap_tier !== capFilter) setCapFilter('ALL');
    if (sectorFilter !== 'ALL' && displaySector(company) !== sectorFilter) setSectorFilter('ALL');
    setHighlightTicker(company.ticker);
    if (highlightTimer.current !== null) window.clearTimeout(highlightTimer.current);
    highlightTimer.current = window.setTimeout(() => setHighlightTicker(null), 2000);
    // Scroll after the cleared query/filters have re-rendered the list.
    window.setTimeout(() => {
      document
        .getElementById(`dirrow-${company.ticker}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 60);
  };

  return (
    <div className="page4">
      <h1 className="phead">Directory</h1>
      <p className="psub">Every tracked stock. Filter by cap tier and sector.</p>
      <div className="dirsearch">
        <span className="dirsearch-glyph" aria-hidden="true">
          ⌕
        </span>
        <input
          type="search"
          className="dirsearch-input"
          placeholder="Search companies…"
          aria-label="Search companies"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setDropdownOpen(true);
          }}
          onFocus={() => setDropdownOpen(true)}
          onBlur={() => window.setTimeout(() => setDropdownOpen(false), 120)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && suggestions.length > 0) jumpTo(suggestions[0]);
            if (event.key === 'Escape') setDropdownOpen(false);
          }}
        />
        {suggestions.length > 0 && (
          <div className="dirsearch-drop" role="listbox" aria-label="Company suggestions">
            {suggestions.map((company) => {
              const rank = liveCaps.get(company.ticker)?.rank;
              return (
                <div
                  className="dirsearch-item"
                  role="option"
                  aria-selected="false"
                  key={company.ticker}
                  // mousedown, not click: it fires before the input's blur
                  // closes the dropdown.
                  onMouseDown={(event) => {
                    event.preventDefault();
                    jumpTo(company);
                  }}
                >
                  <LogoV4 logoUrl={company.logo_url} ticker={company.ticker} name={company.name} />
                  <span className="ds-name">{company.name}</span>
                  <span className="ds-meta">
                    {company.ticker.split('.')[0]}
                    {rank !== undefined ? ` · #${rank}` : ''}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <div className="texttabs">
        <select
          aria-label="Cap tier filter"
          value={capFilter}
          onChange={(event) => setCapFilter(event.target.value as CapTier | 'ALL')}
        >
          {CAP_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option === 'ALL' ? 'All caps' : option}
            </option>
          ))}
        </select>
        <select
          aria-label="Sector filter"
          value={sectorFilter}
          onChange={(event) => setSectorFilter(event.target.value)}
        >
          {sectors.map((sector) => (
            <option key={sector} value={sector}>
              {sector === 'ALL' ? 'All sectors' : sector.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
      </div>
      {error !== null && <p className="empty4">{error}</p>}
      {companies !== null && filtered.length === 0 && (
        <p className="empty4">No companies match these filters.</p>
      )}
      {filtered.map((company) => {
        const live = liveCaps.get(company.ticker);
        return (
          <div
            className={`entry4 ${highlightTicker === company.ticker ? 'flash' : ''}`}
            id={`dirrow-${company.ticker}`}
            key={company.ticker}
            onClick={() => onOpenDeepDive(company.ticker)}
          >
            {live && <span className="rank4">{live.rank}</span>}
            <LogoV4 logoUrl={company.logo_url} ticker={company.ticker} name={company.name} />
            <div className="ebody">
              <div className="etop">
                <span className="ename">{company.name}</span>
                {company.cap_tier !== null && <span className="gtag">{company.cap_tier}</span>}
              </div>
              <div className="emeta">
                <span>{company.ticker}</span>
                <span>{displaySector(company).replace(/_/g, ' ')}</span>
                {live && (
                  <span className={live.source === 'live' ? 'capval live' : 'capval'}>
                    {formatMarketCap(live.marketCap)}
                    {live.source === 'live' ? ' · live' : ''}
                  </span>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ---------- PORTFOLIO ---------- */

export function PortfolioV4({ onOpenDeepDive }: { onOpenDeepDive: (ticker: string, alertId?: number) => void }) {
  const { token } = useAuth();
  const [overlay, setOverlay] = useState<Awaited<ReturnType<typeof getPortfolioOverlay>> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    getPortfolioOverlay(token)
      .then((result) => {
        if (!cancelled) setOverlay(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="page4">
      <h1 className="phead">Portfolio</h1>
      <p className="psub">Your holdings, and which of today's news touches them.</p>
      {!token && (
        <p className="empty4">
          <Link to="/login">Sign in</Link> to see which of today's news touches your holdings.
        </p>
      )}
      {error !== null && <p className="empty4">{error}</p>}
      {token && overlay !== null && (
        <>
          <p className="pfcount">
            {overlay.affected_count}
            <small> / {overlay.holdings.length} holdings touched by today's news</small>
          </p>
          {overlay.holdings.length === 0 && (
            <p className="empty4">
              No holdings yet. <Link to="/holdings">Add your holdings</Link> to light up the
              portfolio thread across the feed.
            </p>
          )}
          {overlay.holdings.map((holding) => (
            <div
              className="entry4"
              key={holding.ticker}
              onClick={() => onOpenDeepDive(holding.ticker, holding.affected_alert_id ?? undefined)}
            >
              <LogoV4 logoUrl={holding.logo_url} ticker={holding.ticker} name={holding.name} />
              <div className="ebody">
                <div className="etop">
                  <span className="ename">{holding.name}</span>
                  <span className="emetric">{holding.quantity} sh</span>
                </div>
                <p className="ewhy">{holding.affected_headline ?? 'No news today.'}</p>
                <div className="emeta">
                  <span>{holding.ticker}</span>
                </div>
              </div>
            </div>
          ))}
        </>
      )}
      <p className="emeta" style={{ marginTop: 24 }}>
        Holdings sync each morning via Account Aggregator (Sahamati) consent — never PAN scraping.
        Encrypted at rest and in transit.
      </p>
    </div>
  );
}

/* ---------- REVIEW ---------- */

const DAY_LABELS = ['−1', '0', '+1', '+2', '+3'];

const OUTCOME_LABELS: Record<CarReviewRow['outcome_label'], string> = {
  HELD: 'Held',
  REVERSED: 'Faded',
  FLAT: 'Flat',
};

export function ReviewV4() {
  const { token } = useAuth();
  const [rows, setRows] = useState<CarReviewRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    getCarReview(token)
      .then((result) => {
        if (!cancelled) setRows(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="page4">
      <h1 className="phead">Reaction review</h1>
      <p className="psub">Did a flagged reaction hold or reverse? Cumulative abnormal return, −1 to +3 days.</p>
      {!token && (
        <p className="empty4">
          <Link to="/login">Sign in</Link> to review how flagged reactions played out.
        </p>
      )}
      {error !== null && <p className="empty4">{error}</p>}
      {token && rows !== null && rows.length === 0 && (
        <p className="empty4">
          No completed reaction windows yet — outcomes appear a few trading days after each alert.
        </p>
      )}
      {token &&
        rows?.map((row) => {
          const series = row.car_series;
          const max = series ? Math.max(...series.map((value) => Math.abs(value)), 0.001) : null;
          return (
            <div className="carrow4" key={row.id}>
              <p className="chl">{row.article_title}</p>
              <div className="emeta" style={{ marginBottom: 12 }}>
                <span>{row.ticker}</span>
                <span className="gtag">{OUTCOME_LABELS[row.outcome_label]}</span>
                <span className={row.car_pct >= 0 ? 'up' : 'down'}>CAR {fmtPct(row.car_pct)}</span>
              </div>
              {series !== null && max !== null && (
                <>
                  <div className="cartrack4">
                    {series.map((value, index) => (
                      <div key={index} style={{ justifyContent: value >= 0 ? 'flex-end' : 'flex-start' }}>
                        <div
                          className={`carbar4 ${value >= 0 ? 'up' : 'down'}`}
                          style={{
                            height: `${(Math.abs(value) / max) * 100}%`,
                            background: value >= 0 ? 'var(--data-up)' : 'var(--data-down)',
                          }}
                        />
                      </div>
                    ))}
                  </div>
                  <div className="carlbl4">
                    {DAY_LABELS.slice(0, series.length).map((label) => (
                      <span key={label}>{label}</span>
                    ))}
                  </div>
                </>
              )}
            </div>
          );
        })}
      <p className="emeta" style={{ marginTop: 24 }}>
        Used to back-validate intensity weights — not a recommendation.
      </p>
    </div>
  );
}
