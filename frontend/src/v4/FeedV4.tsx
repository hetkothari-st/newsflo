/* v4 broadsheet feed: the day's measured stories as a newspaper front
   page. Lead story gets the hero treatment (giant serif headline +
   halftone plate); the rest run as ruled editorial rows. Expanding a
   story unfolds a full-bleed ink band -- "THE RIPPLE" stamped in
   condensed caps -- with the affected companies as ruled text rows and
   the timeline beneath. Data comes from the same feed-v2 endpoints as
   the v3 shell; filter semantics (cap_tiers story match + row-level
   narrowing) are identical. */
import { useCallback, useEffect, useRef, useState } from 'react';
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

function fmtPct(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

function moveClass(value: number): string {
  return value < 0 ? 'down' : 'up';
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
      <span>{alert.category.replace(/_/g, ' ')}</span>
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
  onClose,
  onOpenDeepDive,
}: {
  alert: FeedAlert;
  detail: AlertDetail | null;
  onClose: () => void;
  onOpenDeepDive: (ticker: string, alertId?: number) => void;
}) {
  // The cap filter lives inside each story's affected-companies section
  // (user decision) -- per-card state, narrowing only this ripple's rows.
  const [capFilter, setCapFilter] = useState<CapTier | 'ALL'>('ALL');
  const visibleRows = (layer: RippleLayer) =>
    capFilter === 'ALL' ? layer.rows : layer.rows.filter((row) => row.cap_tier === capFilter);
  const anyRows = detail !== null && detail.layers.some((layer) => visibleRows(layer).length > 0);
  // Swipe right anywhere on the ripple page -> back to the story, the
  // same gesture the deployed card-flip uses.
  const touchX = useRef<number | null>(null);
  return (
    <div
      className="band"
      role="dialog"
      aria-label="Affected companies"
      onClick={onClose}
      onTouchStart={(event) => {
        touchX.current = event.touches[0].clientX;
      }}
      onTouchEnd={(event) => {
        if (touchX.current === null) return;
        const dx = event.changedTouches[0].clientX - touchX.current;
        touchX.current = null;
        if (dx > 55) onClose();
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
      <div className="bandfilters" role="group" aria-label="Cap tier filter">
        <span className="bflab">Cap tier</span>
        {BAND_CAP_FILTERS.map(({ cap, label, title }) => (
          <button
            key={cap}
            className={capFilter === cap ? 'on' : ''}
            onClick={(event) => {
              event.stopPropagation();
              setCapFilter(cap);
            }}
            aria-label={`Cap filter ${cap}`}
            title={title}
          >
            {label}
          </button>
        ))}
      </div>
      {detail === null && <p className="bandempty">Setting the type…</p>}
      {detail !== null && !anyRows && (
        <p className="bandempty">
          No companies in this cap tier for this story. Tap “All” to see everyone affected.
        </p>
      )}
      {detail?.layers.map((layer, layerIndex) => {
        const rows = visibleRows(layer);
        if (rows.length === 0) return null;
        return (
          <div className="layer4" key={`${layer.title}-${layerIndex}`}>
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
                  // row must open its deep dive instead.
                  event.stopPropagation();
                  onOpenDeepDive(row.ticker, alert.id);
                }}
              >
                <LogoV4 logoUrl={row.logo_url} ticker={row.ticker} />
                <div className="cbody">
                  <div className="cmain">
                    <span className="nm4">{row.name}</span>
                    {row.is_exposure_only || row.excess_move_pct == null ? (
                      <span className="mv4 mvx">exposure</span>
                    ) : (
                      <span className={`mv4 ${moveClass(row.excess_move_pct)}`}>
                        {fmtPct(row.excess_move_pct)}
                      </span>
                    )}
                  </div>
                  <div className="cmeta">
                    <span>{row.ticker}</span>
                    {row.cap_tier !== null && <span>{row.cap_tier} cap</span>}
                  </div>
                </div>
              </div>
            ))}
            </div>
          </div>
        );
      })}
      {detail !== null && detail.timeline.length > 0 && (
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
  onEdition,
  onOpenDeepDive,
  onBandOpenChange,
}: {
  // null = today (with latest-edition fallback); YYYY-MM-DD = a back
  // issue picked from the archive, fetched exactly, no fallback.
  date: string | null;
  onEdition: (edition: { count: number; date: string | null }) => void;
  onOpenDeepDive: (ticker: string, alertId?: number) => void;
  // Lets the shell drop scroll-snapping while a ripple band is open --
  // mandatory snap would fight scrolling through a tall band.
  onBandOpenChange: (open: boolean) => void;
}) {
  const { token } = useAuth();
  const [alerts, setAlerts] = useState<FeedAlert[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [details, setDetails] = useState<Record<number, AlertDetail>>({});

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

  // Swipe left on a card -> its ripple page (mirrors the deployed
  // card-flip gesture; tap on the headline/CTA still works everywhere).
  const cardTouchX = useRef<number | null>(null);
  const onCardTouchStart = (event: React.TouchEvent) => {
    cardTouchX.current = event.touches[0].clientX;
  };
  const onCardTouchEnd = (alertId: number) => (event: React.TouchEvent) => {
    if (cardTouchX.current === null) return;
    const dx = event.changedTouches[0].clientX - cardTouchX.current;
    cardTouchX.current = null;
    if (dx < -55 && openId !== alertId) toggle(alertId);
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
            onClick={() => toggle(alert.id)}
            onTouchStart={onCardTouchStart}
            onTouchEnd={onCardTouchEnd(alert.id)}
          >
            <div>
              <div className={`lmove ${moveClass(alert.excess_move_pct)}`}>
                {alert.excess_move_pct < 0 ? '▼' : '▲'} {Math.abs(alert.excess_move_pct).toFixed(1)}%
              </div>
              {/* No own handler: the whole card is clickable and this
                  would double-toggle via bubbling. */}
              <h1>{alert.article.title}</h1>
              <p className="lgist">{alert.summary_short ?? alert.summary_long ?? ''}</p>
              <MetaLine alert={alert} onToggle={() => toggle(alert.id)} />
            </div>
            <Plate src={alert.article.image_url} category={alert.category} className="lplate" />
          </div>
          {openId === alert.id && (
            <RippleBand
              alert={alert}
              detail={details[alert.id] ?? null}
              onClose={closeBand}
              onOpenDeepDive={onOpenDeepDive}
            />
          )}
        </div>
      ))}
    </div>
  );
}
