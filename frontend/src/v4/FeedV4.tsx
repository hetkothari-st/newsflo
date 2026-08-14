/* v4 broadsheet feed: the day's measured stories as a newspaper front
   page. Lead story gets the hero treatment (giant serif headline +
   halftone plate); the rest run as ruled editorial rows. Expanding a
   story unfolds a full-bleed ink band -- "THE RIPPLE" stamped in
   condensed caps -- with the affected companies as ruled text rows and
   the timeline beneath. Data comes from the same feed-v2 endpoints as
   the v3 shell; filter semantics (cap_tiers story match + row-level
   narrowing) are identical. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getAlertDetail,
  getCalendarCounts,
  getFeedAlerts,
  type AlertDetail,
  type CapTier,
  type FeedAlert,
  type RippleLayer,
} from '../v3/api';
import { categoryArtUrl } from '../v3/categoryArt';
import ExpandableTitle from './ExpandableTitle';
import type { InfoV4Data } from './InfoV4';
import LogoV4 from './LogoV4';
import { useAuth } from '../lib/auth';

/* Monochrome plate with the v3 fallback chain: the story's own photo,
   then curated category artwork (publishers that block scraping), then
   nothing -- a broken-image glyph must never reach the page. */
function Plate({ src, category, className }: { src: string | null; category: string; className: string }) {
  const [stage, setStage] = useState<'story' | 'category' | 'none'>(src !== null ? 'story' : 'category');
  const resolved = stage === 'story' ? src : stage === 'category' ? categoryArtUrl(category) : null;
  if (resolved === null) return null;
  return (
    <img
      key={resolved}
      className={className}
      src={resolved}
      alt=""
      loading="lazy"
      onError={() => setStage(stage === 'story' ? 'category' : 'none')}
    />
  );
}

/* When today's edition is empty (market holiday, early morning, stale
   dev copy of the DB), fall back to the most recent day whose FEED has
   stories -- a broadsheet always shows its latest edition, never a
   blank page. Calendar counts include unmeasured alerts the feed
   omits, so each candidate day is verified with a real feed fetch;
   walks up to three months and ten candidate days. Returns
   {date, alerts} or null when the archive is empty too. */
async function findLatestEdition(
  token: string | null,
): Promise<{ date: string; alerts: FeedAlert[] } | null> {
  const now = new Date();
  let year = now.getFullYear();
  let month = now.getMonth() + 1;
  let attempts = 0;
  for (let hop = 0; hop < 3 && attempts < 10; hop++) {
    const counts = await getCalendarCounts(year, month);
    const days = Object.keys(counts)
      .filter((day) => counts[day] > 0)
      .sort()
      .reverse();
    for (const day of days) {
      if (attempts >= 10) break;
      attempts += 1;
      const alerts = await getFeedAlerts(token, { lang: 'en', date: day });
      if (alerts.length > 0) return { date: day, alerts };
    }
    month -= 1;
    if (month === 0) {
      month = 12;
      year -= 1;
    }
  }
  return null;
}

/* Null-tolerant (finding I5): an honest-unavailable measurement serves
   raw_move_pct/sector_move_pct as null, and a dash is the only truthful
   rendering -- 0.0% would state a measurement nobody made. */
function fmtPct(value: number | null | undefined): string {
  if (value == null) return '—';
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

function moveClass(value: number | null | undefined): string {
  // 0.0 is flat, not up -- a zero excess move must never render as a
  // green gain (one-source-of-truth spec §39). null is flat too: no
  // measurement is not a gain or a loss.
  if (value == null) return 'flat';
  return value < 0 ? 'down' : value > 0 ? 'up' : 'flat';
}

/* Reaction color from the server's dead-zone-classified direction --
   the ONLY semantic source (spec §37). A missing reaction_direction
   renders neutral/flat; it is never re-derived from the raw excess
   sign (that fallback used to make a +0.02% noise move flash green). */
export function reactionClass(reaction: { direction: string } | null | undefined): string {
  if (!reaction) return 'flat';
  if (reaction.direction === 'positive') return 'up';
  if (reaction.direction === 'negative') return 'down';
  return 'flat';
}

/* Arrow glyph from the SAME source as the color -- never a separate
   sign check on the raw number (spec §37/§39: color and arrow must
   never disagree). */
export function reactionArrow(reaction: { direction: string } | null | undefined): string {
  if (!reaction) return '';
  if (reaction.direction === 'positive') return '▲';
  if (reaction.direction === 'negative') return '▼';
  return '';
}

/* Fundamental-impact glyph -- driven ONLY by economic_effect, never by
   the price move (spec §38: Apollo is not a "winner" because its stock
   is green). */
function effectGlyph(effect: string): string {
  if (effect === 'positive') return '▲';
  if (effect === 'negative') return '▼';
  return '◆';
}

/* Row-level directness + tier line (spec §28, Task 9): a second compact
   line under the existing "EFFECT · GRADE" line, e.g.
   "DIRECT EXPOSURE · PRIMARY" / "INDIRECT EXPOSURE · RIPPLE" /
   "REMOTE · MACRO". REMOTE drops the "EXPOSURE" suffix (per the brief's
   worked examples); publication_tier's secondary_ripple spelling AND its
   dead legacy names ('secondary_deep_dive'/'secondary') all display as
   RIPPLE -- only 'primary' and 'macro_context' get their own word. */
function directnessWord(directness: string): string {
  return directness === 'REMOTE' ? 'REMOTE' : `${directness} EXPOSURE`;
}

function tierWord(tier: string): string {
  if (tier === 'primary') return 'PRIMARY';
  if (tier === 'macro_context') return 'MACRO';
  return 'RIPPLE';
}

function fmtISTTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Kolkata',
  });
}

function MetaLine({ alert, onToggle }: { alert: FeedAlert; onToggle: () => void }) {
  return (
    <div className="metaline">
      <span>{alert.article.source}</span>
      <span>—</span>
      <span>{fmtISTTime(alert.created_at)} IST</span>
      <span>—</span>
      <span>{alert.category_label ?? alert.category.replace(/_/g, ' ')}</span>
      {alert.exposure === 'indirect_only' && (
        /* Owner decision 2026-08-14: no-primary gated alerts appear in the
           feed but must be unmistakably labeled -- every company on this
           story is indirect (secondary/deep-dive) exposure, none is the
           article's subject. Final-blueprint §15 (Task 9): when the
           article's mechanisms span multiple sectors, labeling it as one
           company's "indirect exposure" misstates it -- event_scope
           carries a controlled event descriptor instead. */
        <>
          <span>—</span>
          <span className="indirect4" title="No directly-affected company: every listed company has indirect exposure only">
            {alert.event_scope === 'multi_sector' ? 'Multi-sector impact' : 'Indirect exposure'}
          </span>
        </>
      )}
      {alert.in_my_holdings && (
        <>
          <span>—</span>
          <span>Held</span>
        </>
      )}
      <span
        className="aff"
        role="button"
        tabIndex={0}
        onClick={(event) => {
          event.stopPropagation();
          onToggle();
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') onToggle();
        }}
      >
        See who's affected →
      </span>
    </div>
  );
}

const BAND_CAP_FILTERS: Array<{ cap: CapTier | 'ALL'; label: string; title: string }> = [
  { cap: 'ALL', label: 'ALL', title: 'All companies' },
  { cap: 'LARGE', label: 'L', title: 'Large cap (top 100 by market cap)' },
  { cap: 'MID', label: 'M', title: 'Mid cap (rank 101–250)' },
  { cap: 'SMALL', label: 'S', title: 'Small cap (rank 251–500)' },
  { cap: 'MICRO', label: 'µ', title: 'Micro cap (rank 501+)' },
];

function RippleBand({
  alert,
  detail,
  capFilter,
  onCapFilter,
  onClose,
  onOpenDeepDive,
  onOpenInfo,
}: {
  alert: FeedAlert;
  detail: AlertDetail | null;
  // Shared across every story's ripple and PERSISTS between them (user
  // decision) -- lives in FeedV4, not per band.
  capFilter: CapTier | 'ALL';
  onCapFilter: (cap: CapTier | 'ALL') => void;
  onClose: () => void;
  onOpenDeepDive: (ticker: string, alertId?: number) => void;
  onOpenInfo: (info: InfoV4Data) => void;
}) {
  const navigate = useNavigate();
  // Two swipeable sub-sections: Affected companies / Timeline.
  const [tab, setTab] = useState<'companies' | 'timeline'>('companies');
  const visibleRows = (layer: RippleLayer) =>
    capFilter === 'ALL' ? layer.rows : layer.rows.filter((row) => row.cap_tier === capFilter);
  const anyRows = detail !== null && detail.layers.some((layer) => visibleRows(layer).length > 0);
  // Gesture chain (user decision): a leftward drag moves forward
  // (companies -> timeline); a rightward drag ALWAYS returns to the main
  // news feed, from either tab (timeline -> companies is a tab tap).
  // Clicks never flip; the buttons remain for mouse users. A gesture
  // only counts as a horizontal swipe when the horizontal travel clearly
  // dominates the vertical -- otherwise scrolling a long company list
  // with a little sideways drift would fling the reader back.
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  return (
    <div
      className="band"
      role="dialog"
      aria-label="Affected companies"
      onTouchStart={(event) => {
        touchStart.current = { x: event.touches[0].clientX, y: event.touches[0].clientY };
      }}
      onTouchEnd={(event) => {
        if (touchStart.current === null) return;
        const dx = event.changedTouches[0].clientX - touchStart.current.x;
        const dy = event.changedTouches[0].clientY - touchStart.current.y;
        touchStart.current = null;
        if (Math.abs(dx) < 55 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
        if (dx < 0 && tab === 'companies') setTab('timeline');
        else if (dx > 0) onClose();
      }}
    >
      <button className="bandclose" onClick={onClose}>
        Back to the story ×
      </button>
      <div className="stamp">The Ripple</div>
      <p className="bandhl">{alert.article.title}</p>
      <div className="sumline">
        <span>
          Raw <b className={moveClass(alert.raw_move_pct)}>{fmtPct(alert.raw_move_pct)}</b>
        </span>
        <span>
          Sector <b className={moveClass(alert.sector_move_pct)}>{fmtPct(alert.sector_move_pct)}</b>
        </span>
        <span>
          Volume <b>{alert.volume_multiple === null ? '—' : `${alert.volume_multiple.toFixed(1)}×`}</b>
        </span>
      </div>
      {/* Sub-section tabs -- also swipeable (left/right). Active gains
          scale, never color, like every other tab in the app. */}
      <div className="bandtabs" role="tablist" aria-label="Ripple sections">
        <button
          role="tab"
          aria-selected={tab === 'companies'}
          className={tab === 'companies' ? 'on' : ''}
          onClick={(event) => {
            event.stopPropagation();
            setTab('companies');
          }}
        >
          Affected companies
        </button>
        <button
          role="tab"
          aria-selected={tab === 'timeline'}
          className={tab === 'timeline' ? 'on' : ''}
          onClick={(event) => {
            event.stopPropagation();
            setTab('timeline');
          }}
        >
          Timeline
        </button>
        <button
          className="chartsbtn"
          onClick={(event) => {
            event.stopPropagation();
            navigate(`/v4/charts/${alert.id}`);
          }}
          aria-label="Impact charts"
        >
          Charts ↗
        </button>
      </div>
      {/* Floating cap-tier rail (user decision: reachable like Insta
          story controls, no trip to the top). Fixed to the right edge,
          persists across stories via lifted state. */}
      {tab === 'companies' && (
        <div className="caprail" role="group" aria-label="Cap tier filter">
          {BAND_CAP_FILTERS.map(({ cap, label, title }) => (
            <button
              key={cap}
              className={capFilter === cap ? 'on' : ''}
              onClick={(event) => {
                event.stopPropagation();
                onCapFilter(cap);
              }}
              aria-label={`Cap filter ${cap}`}
              title={title}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      {detail === null && <p className="bandempty">Loading…</p>}
      {tab === 'companies' && detail !== null && !anyRows && (
        <p className="bandempty">
          No companies in this cap tier for this story. Tap “All” to see everyone affected.
        </p>
      )}
      {tab === 'companies' &&
        detail?.layers.map((layer, layerIndex) => {
        const rows = visibleRows(layer);
        if (rows.length === 0) return null;
        // Final-blueprint §29 (Task 9): macro-context sections must read as
        // visually distinct from primary/ripple ones -- ripple_layers.py
        // prefixes the relationship string "MACRO:<label>" for these.
        const isMacro = layer.relationship.startsWith('MACRO:');
        return (
          <div className={`layer4${isMacro ? ' macro4' : ''}`} key={`${layer.title}-${layerIndex}`}>
            {/* Full-bleed ink strip -- the reference's own sectioning
                device (paper/ink inversion), so each layer reads as an
                unmistakable section, not a floating heading. */}
            <div className="lhead4">
              <span className={`li4 ${layer.icon}`} aria-hidden="true">
                {layer.icon === 'win' ? '▲' : layer.icon === 'lose' ? '▼' : '◆'}
              </span>
              <span>{layer.title}</span>
            </div>
            <div className="lbody4">
            {layer.note !== null && <p className="lnote4">{layer.note}</p>}
            {rows.map((row) => (
              <div
                className="crow"
                key={row.ticker}
                data-testid={`v4row-${row.ticker}`}
                onClick={(event) => {
                  // The page background flips back on click -- a company
                  // row must open its deep dive instead. Demo stories
                  // (negative preview-only ids) have no Alert row to give
                  // the deep dive story context, so none is passed.
                  event.stopPropagation();
                  onOpenDeepDive(row.ticker, alert.id);
                }}
              >
                <LogoV4 logoUrl={row.logo_url} ticker={row.ticker} name={row.name} />
                <div className="cbody">
                  <div className="cmain">
                    {row.economic_effect && (
                      /* Fundamental impact -- separate truth from the
                         price number to its right (spec §38/§65). */
                      <span
                        className={`fx4 ${row.economic_effect}`}
                        title={`Fundamental impact: ${row.economic_effect}`}
                      >
                        {effectGlyph(row.economic_effect)}
                      </span>
                    )}
                    <span className="nm4">{row.name}</span>
                    {row.is_exposure_only || row.excess_move_pct == null ? (
                      <span className="mv4 mvx">exposure</span>
                    ) : (
                      <span
                        className={`mv4 ${reactionClass(
                          row.reaction_direction ? { direction: row.reaction_direction } : null,
                        )}`}
                      >
                        {fmtPct(row.excess_move_pct)}
                      </span>
                    )}
                  </div>
                  {row.economic_effect && row.materiality_grade && (
                    /* Authoritative fundamental verdict + gate confidence
                       -- text label, not just the glyph, so the reader
                       gets the tier without opening the deep dive. */
                    <div className={`fxl4 ${row.economic_effect}`}>
                      {row.economic_effect.toUpperCase()} · {row.materiality_grade}
                    </div>
                  )}
                  {row.causal_directness && row.publication_tier && (
                    /* Second five-dimension line (spec §28, Task 9):
                       directness and publication tier are independent
                       dimensions from the effect/grade line above -- a
                       DIRECT exposure can still publish at RIPPLE tier.
                       Absent on legacy rows (no field, no line, never a
                       guess). */
                    <div className="dtl4">
                      {directnessWord(row.causal_directness)} · {tierWord(row.publication_tier)}
                    </div>
                  )}
                  {row.mechanism && <div className="mch4">{row.mechanism}</div>}
                  {row.divergence && <p className="dvg4">{row.divergence}</p>}
                  <div className="cmeta">
                    <span>{row.ticker}</span>
                    {row.cap_tier !== null && <span>{row.cap_tier} cap</span>}
                    {row.confidence_band && (
                      /* Band-only confidence display (ruling R4): never a
                         numeric confidence_score, which no v4 row type
                         even carries. */
                      <span className="cband4" title={`Confidence: ${row.confidence_band}`}>
                        {row.confidence_band}
                      </span>
                    )}
                  </div>
                </div>
                {/* (i) = glance and stay; the row itself = go deep --
                    same split as the deployed shell. */}
                <button
                  className="ib4"
                  aria-label={`About ${row.ticker}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onOpenInfo({
                      name: row.name,
                      ticker: row.ticker,
                      sector: row.sector,
                      logoUrl: row.logo_url,
                      fundamentals: row.fundamentals,
                      businessDesc: row.business_desc,
                      businessDescSourceUrl: row.business_desc_source_url,
                      volatilityRange: row.volatility_range,
                    });
                  }}
                >
                  i
                </button>
              </div>
            ))}
            </div>
          </div>
        );
        })}
      {tab === 'timeline' && detail !== null && detail.timeline.length === 0 && (
        <p className="bandempty">No timeline analysis for this story yet.</p>
      )}
      {tab === 'timeline' && detail !== null && detail.timeline.length > 0 && (
        <div className="layer4">
          <div className="lhead4">
            <span className="li4" aria-hidden="true">
              ◆
            </span>
            <span>What happens next</span>
          </div>
          <div className="lbody4 tl4">
            {detail.timeline.map((entry, index) => (
              <div className="tlrow4" key={`${entry.horizon}-${index}`}>
                <p className="tlh4">{entry.horizon.replace(/_/g, ' ')}</p>
                <p className="tld4">{entry.description}</p>
              </div>
            ))}
          </div>
        </div>
      )}
      <button className="close4" onClick={onClose}>
        Back to the story ↑
      </button>
    </div>
  );
}

export default function FeedV4({
  date,
  initialOpenId = null,
  onEdition,
  onOpenDeepDive,
  onOpenInfo,
  onBandOpenChange,
}: {
  // null = today (with latest-edition fallback); YYYY-MM-DD = a back
  // issue picked from the archive, fetched exactly, no fallback.
  date: string | null;
  // Reopen this story's ripple as soon as the feed loads (the charts
  // page's way back). Applied once.
  initialOpenId?: number | null;
  onEdition: (edition: { count: number; date: string | null }) => void;
  onOpenDeepDive: (ticker: string, alertId?: number) => void;
  onOpenInfo: (info: InfoV4Data) => void;
  // Lets the shell drop scroll-snapping while a ripple band is open --
  // mandatory snap would fight scrolling through a tall band.
  onBandOpenChange: (open: boolean) => void;
}) {
  const { token } = useAuth();
  const [alerts, setAlerts] = useState<FeedAlert[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [details, setDetails] = useState<Record<number, AlertDetail>>({});
  // Cap filter shared by every story's ripple -- persists across stories.
  const [capFilter, setCapFilter] = useState<CapTier | 'ALL'>('ALL');
  const initialApplied = useRef(false);

  useEffect(() => {
    let cancelled = false;
    setAlerts(null);
    setError(null);
    setOpenId(null);
    onBandOpenChange(false);
    (async () => {
      try {
        let result = await getFeedAlerts(token, { lang: 'en', date: date ?? undefined });
        let editionDate: string | null = date;
        if (result.length === 0 && date === null) {
          const edition = await findLatestEdition(token);
          if (edition !== null) {
            editionDate = edition.date;
            result = edition.alerts;
          }
        }
        if (cancelled) return;
        setAlerts(result);
        onEdition({ count: result.length, date: editionDate });
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, date, onEdition, onBandOpenChange]);

  const toggle = useCallback(
    (alertId: number) => {
      const next = openId === alertId ? null : alertId;
      setOpenId(next);
      // Outside the setState updater: notifying the shell from inside one
      // is a cross-component update during render (React warns).
      onBandOpenChange(next !== null);
      setDetails((current) => {
        if (current[alertId]) return current;
        getAlertDetail(alertId, token, 'en')
          .then((detail) => setDetails((latest) => ({ ...latest, [alertId]: detail })))
          .catch(() => {
            /* band keeps its setting-the-type state */
          });
        return current;
      });
    },
    [openId, token, onBandOpenChange],
  );

  const closeBand = useCallback(() => {
    setOpenId(null);
    onBandOpenChange(false);
  }, [onBandOpenChange]);

  // One-shot: returning from the charts page reopens that story's ripple.
  useEffect(() => {
    if (initialApplied.current || initialOpenId === null || alerts === null) return;
    initialApplied.current = true;
    if (alerts.some((alert) => alert.id === initialOpenId)) toggle(initialOpenId);
  }, [alerts, initialOpenId, toggle]);

  // Leftward drag on a card -> its affected-companies page (user
  // decision; the "See who's affected" tap remains for mouse users).
  // Horizontal travel must clearly dominate vertical, so feed scrolling
  // between cards never opens a ripple by accident.
  const cardTouch = useRef<{ x: number; y: number } | null>(null);
  const onCardTouchStart = (event: React.TouchEvent) => {
    cardTouch.current = { x: event.touches[0].clientX, y: event.touches[0].clientY };
  };
  const onCardTouchEnd = (alertId: number) => (event: React.TouchEvent) => {
    if (cardTouch.current === null) return;
    const dx = event.changedTouches[0].clientX - cardTouch.current.x;
    const dy = event.changedTouches[0].clientY - cardTouch.current.y;
    cardTouch.current = null;
    if (Math.abs(dx) < 55 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    if (dx < 0 && openId !== alertId) toggle(alertId);
  };

  if (error !== null) return <p className="empty4">{error}</p>;
  if (alerts !== null && alerts.length === 0)
    return <p className="empty4">No measured stories yet today. New editions appear as the market reacts.</p>;

  // Every story gets the full front-page treatment (user decision) --
  // one full-viewport snap slot per card, Inshorts-style.
  return (
    <div>
      {alerts?.map((alert, index) => (
        <div key={alert.id}>
          {/* The first card shares the homepage with the masthead, so it
              runs compact -- natural height, bounded plate -- and is fully
              visible without scrolling. Cards after it get the full
              viewport slot. */}
          <div
            className={`storycard ${index === 0 ? 'first' : ''}`}
            data-testid={`v4story-${alert.id}`}
            onTouchStart={onCardTouchStart}
            onTouchEnd={onCardTouchEnd(alert.id)}
          >
            <div>
              {alert.excess_move_pct == null ? (
                /* Strict engine (spec §49): fundamental analysis stays
                   visible when the price feed failed -- honest dash,
                   never a fabricated number. */
                <div className="lmove flat">—</div>
              ) : (
                <div className={`lmove ${reactionClass(alert.market_reaction)}`}>
                  {reactionArrow(alert.market_reaction)}{' '}
                  {Math.abs(alert.excess_move_pct).toFixed(1)}%
                </div>
              )}
              <ExpandableTitle title={alert.article.title} />
              <p className="lgist">{alert.summary_short ?? alert.summary_long ?? ''}</p>
              <MetaLine alert={alert} onToggle={() => toggle(alert.id)} />
            </div>
            <Plate src={alert.article.image_url} category={alert.category} className="lplate" />
          </div>
          {openId === alert.id && (
            <RippleBand
              alert={alert}
              detail={details[alert.id] ?? null}
              capFilter={capFilter}
              onCapFilter={setCapFilter}
              onClose={closeBand}
              onOpenDeepDive={onOpenDeepDive}
              onOpenInfo={onOpenInfo}
            />
          )}
        </div>
      ))}
    </div>
  );
}
