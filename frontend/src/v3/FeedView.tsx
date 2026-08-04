/* The vertical card feed (spec v2 §2, §7): card front = skim layer
   (excess move, verdict, headline, gist, meta, "see who's affected"),
   card back = layered ripple + timeline behind mini-tabs. Swipe left
   flips front->back, swipe right flips back; vertical scroll moves
   through stories; taps mirror the swipes on non-touch devices --
   ported from the approved prototype. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getAlertDetail,
  getFeedAlerts,
  type AlertDetail,
  type CapTier,
  type FeedAlert,
  type LayerRow,
  type RippleLayer,
  type TimelineEntry,
} from './api';
import { categoryArtUrl } from './categoryArt';
import StockRow from './StockRow';
import {
  arrow,
  fmtPct,
  fmtTime,
  fmtVolume,
  horizonLabel,
  moveColor,
  moveDir,
  TIMELINE_COLORS,
  verdictClass,
} from './format';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
import type { TranslationKey } from '../lib/i18n';

const VERDICT_KEYS: Record<FeedAlert['verdict'], TranslationKey> = {
  COMPANY_SPECIFIC: 'v3.verdictCompany',
  SECTOR_WIDE: 'v3.verdictSector',
  UNCONFIRMED: 'v3.verdictUnconfirmed',
};

function LayerBlock({
  layer,
  capFilter,
  onOpenDeepDive,
  onOpenInfo,
}: {
  layer: RippleLayer;
  capFilter: CapTier | 'ALL';
  onOpenDeepDive: (ticker: string) => void;
  onOpenInfo: (row: LayerRow) => void;
}) {
  // The top-bar cap filter narrows the company rows too, not just which
  // stories survive. Rows without an honest tier (foreign listings, stale
  // caps) match only "All". A section left with no rows hides entirely --
  // the 3-tier sectioning mechanism itself is untouched, this is pure
  // presentation-time narrowing.
  const rows =
    capFilter === 'ALL' ? layer.rows : layer.rows.filter((row) => row.cap_tier === capFilter);
  if (rows.length === 0) return null;
  return (
    <div className="layer">
      <div className="lh">
        <span className={`li ${layer.icon}`}>
          {layer.icon === 'win' ? '▲' : layer.icon === 'lose' ? '▼' : '◆'}
        </span>
        <span className="lt">{layer.title}</span>
        <span className="lrel">{layer.relationship.replace(/_/g, ' ')}</span>
      </div>
      {layer.note !== null && <p className="lnote">{layer.note}</p>}
      {rows.map((row) => (
        <StockRow key={row.ticker} row={row} onOpenDeepDive={onOpenDeepDive} onOpenInfo={onOpenInfo} />
      ))}
    </div>
  );
}

function NewsImage({ src, onFail }: { src: string; onFail: () => void }) {
  // Hidden entirely on load failure (via onFail, so the card front also
  // drops its has-img layout) -- a broken-image icon must never reach
  // the card (CLAUDE.md: no silent failures on the canvas).
  return (
    <div className="nimg" data-testid="news-image">
      <img src={src} alt="" loading="lazy" onError={onFail} />
    </div>
  );
}

function TimelineBlock({ timeline }: { timeline: TimelineEntry[] }) {
  if (timeline.length === 0) {
    return <p className="empty">No timeline analysis for this story yet.</p>;
  }
  return (
    <div className="tl">
      {timeline.map((entry, index) => (
        <div className="tlrow" key={`${entry.horizon}-${index}`}>
          <div className="tldot">
            <i style={{ background: TIMELINE_COLORS[entry.horizon] ?? 'var(--ink3)' }} />
            {index < timeline.length - 1 && <span className="ln" />}
          </div>
          <div>
            <p className="tlh">{horizonLabel(entry.horizon)}</p>
            <p className="tld">{entry.description}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function Card({
  alert,
  flipped,
  detail,
  capFilter,
  onFlip,
  onUnflip,
  onOpenDeepDive,
  onOpenInfo,
}: {
  alert: FeedAlert;
  flipped: boolean;
  detail: AlertDetail | null;
  capFilter: CapTier | 'ALL';
  onFlip: () => void;
  onUnflip: () => void;
  onOpenDeepDive: (ticker: string) => void;
  onOpenInfo: (row: LayerRow) => void;
}) {
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [backTab, setBackTab] = useState<'ripple' | 'timeline'>('ripple');
  // True once the flip animation has finished -- drops the 3D transforms
  // so the back face renders as a flat layer with crisp text (see
  // .card.flipped.settled in v3.css). Falls back to a timer where
  // transitionend doesn't fire (test environments, reduced motion).
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    if (!flipped) {
      setSettled(false);
      return;
    }
    const timer = window.setTimeout(() => setSettled(true), 550);
    return () => window.clearTimeout(timer);
  }, [flipped]);
  // 'story' -> the article's own photo; 'category' -> curated thematic
  // artwork for publishers that block photo scraping (or when the story
  // photo fails to load); 'none' -> clean no-image layout (art failed too).
  const [imageStage, setImageStage] = useState<'story' | 'category' | 'none'>(
    alert.article.image_url !== null ? 'story' : 'category',
  );
  const dir = moveDir(alert.excess_move_pct, alert.verdict);
  const imageSrc =
    imageStage === 'story'
      ? alert.article.image_url
      : imageStage === 'category'
        ? categoryArtUrl(alert.category)
        : null;
  const showImage = imageSrc !== null;
  return (
    <div className={`card ${flipped ? 'flipped' : ''} ${settled ? 'settled' : ''}`} data-card={alert.id}>
      <div
        className="flip"
        onTransitionEnd={(event) => {
          if (event.propertyName === 'transform' && flipped) setSettled(true);
        }}
      >
        <div
          className={`face front ${showImage ? 'has-img' : ''}`}
          onClick={onFlip}
          data-testid={`front-${alert.id}`}
        >
          <div className="ftop">
            <div>
              <div className={`move ${dir}`}>
                {arrow(dir)} {Math.abs(alert.excess_move_pct).toFixed(1)}%
              </div>
              <div className="xlabel">{t('v3.excessVsSector')}</div>
            </div>
            <span className={`verdict ${verdictClass(alert.verdict)}`}>
              {t(VERDICT_KEYS[alert.verdict])}
            </span>
          </div>
          <div className="headline">{alert.article.title}</div>
          <div className="gist">{alert.summary_short ?? alert.summary_long ?? ''}</div>
          {showImage && (
            <NewsImage
              key={imageSrc!}
              src={imageSrc!}
              onFail={() => setImageStage(imageStage === 'story' ? 'category' : 'none')}
            />
          )}
          <div className="ffoot">
            <div className="meta">
              <span>{alert.category_label ?? alert.category.replace(/_/g, ' ')}</span>
              <span>·</span>
              <span>{fmtTime(alert.created_at)}</span>
              {alert.in_my_holdings && (
                <>
                  <span className="odot" />
                  <span>{t('v3.held')}</span>
                </>
              )}
            </div>
            <div className="cta">
              <span>{t('v3.seeAffected')}</span>
              <span className="ar">→</span>
            </div>
          </div>
        </div>
        <div className="face back">
          <div className="bhead">
            <div>
              <h3>{alert.article.title}</h3>
              <div className="src">
                {alert.article.source} ·{' '}
                {new Date(alert.created_at).toLocaleDateString('en-IN', {
                  day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata',
                })}
              </div>
            </div>
            {/* Charts entry -- opens the rebuilt deck (features/visualize/
                deck, chart-spec Doc-1/Doc-2 + approved prototype). */}
            <button
              className="bx"
              aria-label="Charts"
              title="Charts"
              onClick={(event) => {
                event.stopPropagation();
                navigate(`/alerts/${alert.id}/charts`);
              }}
            >
              {/* Mini bar-chart glyph -- reads as "charts" at a glance,
                  which the old abstract ◫ box did not. currentColor so it
                  follows the .bx button's own ink in both themes. */}
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" focusable="false">
                <rect x="1" y="8" width="3" height="5" rx="0.5" fill="currentColor" />
                <rect x="5.5" y="4" width="3" height="9" rx="0.5" fill="currentColor" />
                <rect x="10" y="1" width="3" height="12" rx="0.5" fill="currentColor" />
              </svg>
            </button>
            <button
              className="bx"
              aria-label="Back to headline"
              onClick={(event) => {
                event.stopPropagation();
                onUnflip();
              }}
            >
              ×
            </button>
          </div>
          <div className="sumstrip">
            <div className="st">
              <div className="l">{t('v3.raw')}</div>
              <div className="v" style={{ color: moveColor(alert.raw_move_pct) }}>
                {fmtPct(alert.raw_move_pct)}
              </div>
            </div>
            <div className="st">
              <div className="l">{t('v3.sector')}</div>
              <div className="v" style={{ color: moveColor(alert.sector_move_pct) }}>
                {fmtPct(alert.sector_move_pct)}
              </div>
            </div>
            <div className="st">
              <div className="l">{t('v3.volume')}</div>
              <div className="v">{fmtVolume(alert.volume_multiple)}</div>
            </div>
          </div>
          <div className="tabsmini">
            <button className={backTab === 'ripple' ? 'on' : ''} onClick={() => setBackTab('ripple')}>
              {t('v3.tabRipple')}
            </button>
            <button
              className={backTab === 'timeline' ? 'on' : ''}
              onClick={() => setBackTab('timeline')}
            >
              {t('v3.tabTimeline')}
            </button>
          </div>
          <div className="layers">
            {detail === null ? (
              <p className="empty">Loading analysis…</p>
            ) : backTab === 'ripple' ? (
              <>
                {capFilter !== 'ALL' &&
                  !detail.layers.some((layer) =>
                    layer.rows.some((row) => row.cap_tier === capFilter),
                  ) && <p className="empty">{t('v3.noCapCompanies')}</p>}
                {detail.layers.map((layer) => (
                  <LayerBlock
                    key={layer.relationship}
                    layer={layer}
                    capFilter={capFilter}
                    onOpenDeepDive={onOpenDeepDive}
                    onOpenInfo={onOpenInfo}
                  />
                ))}
              </>
            ) : (
              <TimelineBlock timeline={detail.timeline} />
            )}
          </div>
          <div className="bfoot">{t('v3.disclaimer')}</div>
        </div>
      </div>
    </div>
  );
}

export default function FeedView({
  active,
  capFilter,
  date,
  onOpenDeepDive,
  onOpenInfo,
  onAnyFlip,
}: {
  active: boolean;
  capFilter: CapTier | 'ALL';
  // null = today; YYYY-MM-DD reopens that IST day (calendar mechanism).
  date: string | null;
  onOpenDeepDive: (ticker: string, alertId: number) => void;
  onOpenInfo: (row: LayerRow) => void;
  onAnyFlip: () => void;
}) {
  const { token } = useAuth();
  const { language, t, translating } = useLanguage();
  const [alerts, setAlerts] = useState<FeedAlert[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flippedIds, setFlippedIds] = useState<Set<number>>(new Set());
  const [details, setDetails] = useState<Record<number, AlertDetail>>({});
  const feedRef = useRef<HTMLDivElement | null>(null);
  const touchStartX = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setAlerts(null);
    setError(null);
    // Refetches on language switch (server-side translations) and on
    // calendar date change; cached details are dropped so the card backs
    // refetch in the new language/day too.
    setDetails({});
    setFlippedIds(new Set());
    getFeedAlerts(token, { lang: language, date: date ?? undefined })
      .then((result) => {
        if (!cancelled) setAlerts(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [token, language, date]);

  // Live translation updates (no manual refresh): while the on-demand
  // drain runs for a non-English language, silently re-pull the feed every
  // few seconds so translated titles/gists stream in as the backend
  // finishes them, plus one final pull when the drain completes. Silent =
  // the list is REPLACED in place, never blanked -- no flicker, no lost
  // scroll/flip state. Cached card-back details are dropped on completion
  // so reopened backs pick up translated text too.
  useEffect(() => {
    if (language === 'en') return;
    let cancelled = false;
    const refetchSilently = () => {
      getFeedAlerts(token, { lang: language, date: date ?? undefined })
        .then((result) => {
          if (!cancelled) setAlerts(result);
        })
        .catch(() => {
          /* transient poll failure -- keep what's on screen */
        });
    };
    if (translating) {
      const interval = window.setInterval(refetchSilently, 4000);
      return () => {
        cancelled = true;
        window.clearInterval(interval);
      };
    }
    // translating just flipped false (or a fresh non-English mount): pull
    // the final translated state once and refresh detail caches.
    refetchSilently();
    setDetails({});
    return () => {
      cancelled = true;
    };
  }, [translating, language, date, token]);

  const loadDetail = useCallback(
    (alertId: number) => {
      setDetails((current) => {
        if (current[alertId]) return current;
        getAlertDetail(alertId, token, language)
          .then((detail) => {
            setDetails((latest) => ({ ...latest, [alertId]: detail }));
          })
          .catch(() => {
            /* detail stays absent; the back shows its loading state */
          });
        return current;
      });
    },
    [token, language],
  );

  const flip = useCallback(
    (alertId: number) => {
      setFlippedIds((current) => new Set(current).add(alertId));
      loadDetail(alertId);
      onAnyFlip();
    },
    [loadDetail, onAnyFlip],
  );

  const unflip = useCallback((alertId: number) => {
    setFlippedIds((current) => {
      const next = new Set(current);
      next.delete(alertId);
      return next;
    });
  }, []);

  // Touch swipe axis (spec v2 §2): swipe left on the front -> flip to the
  // analysis; swipe right on the back -> return to the headline. Same
  // centered-card resolution as the prototype.
  useEffect(() => {
    const feedEl = feedRef.current;
    if (!feedEl) return;
    const onTouchStart = (event: TouchEvent) => {
      touchStartX.current = event.touches[0].clientX;
    };
    const onTouchEnd = (event: TouchEvent) => {
      if (touchStartX.current == null) return;
      const dx = event.changedTouches[0].clientX - touchStartX.current;
      touchStartX.current = null;
      if (Math.abs(dx) < 55) return;
      const centered = document
        .elementFromPoint(window.innerWidth / 2, window.innerHeight / 2)
        ?.closest('[data-card]');
      if (!centered) return;
      const alertId = Number((centered as HTMLElement).dataset.card);
      if (Number.isNaN(alertId)) return;
      if (dx < 0 && !centered.classList.contains('flipped')) flip(alertId);
      else if (dx > 0 && centered.classList.contains('flipped')) unflip(alertId);
    };
    feedEl.addEventListener('touchstart', onTouchStart, { passive: true });
    feedEl.addEventListener('touchend', onTouchEnd);
    return () => {
      feedEl.removeEventListener('touchstart', onTouchStart);
      feedEl.removeEventListener('touchend', onTouchEnd);
    };
  }, [flip, unflip]);

  // A story matches the cap filter when ANY tagged company sits in the
  // chosen tier (cap_tiers, from the backend), not only the peak mover.
  // peak_cap_tier is the fallback for stale cached responses that predate
  // the cap_tiers field. Deliberately independent of loaded card-back
  // details -- the visible card set must not change when a card is flipped.
  const isVisible = useCallback(
    (alert: FeedAlert): boolean => {
      if (capFilter === 'ALL') return true;
      if (alert.cap_tiers) return alert.cap_tiers.includes(capFilter);
      return alert.peak_cap_tier === capFilter;
    },
    [capFilter],
  );

  const visibleAlerts = (alerts ?? []).filter(isVisible);

  return (
    <div className={`view ${active ? 'on' : ''}`}>
      {/* locked while any card shows its analysis -- scrolling past the end
          of the companies list must never advance to the next story. */}
      <div className={`feed ${flippedIds.size > 0 ? 'locked' : ''}`} ref={feedRef} data-testid="feed">
        {error !== null && <p className="empty">{error}</p>}
        {alerts !== null && alerts.length === 0 && <p className="empty">{t('v3.noStories')}</p>}
        {alerts !== null && alerts.length > 0 && visibleAlerts.length === 0 && (
          <p className="empty">{t('v3.noCapMatch')}</p>
        )}
        {visibleAlerts.map((alert) => (
          <div className="slot" key={alert.id}>
            <Card
              alert={alert}
              flipped={flippedIds.has(alert.id)}
              detail={details[alert.id] ?? null}
              capFilter={capFilter}
              onFlip={() => flip(alert.id)}
              onUnflip={() => unflip(alert.id)}
              onOpenDeepDive={(ticker) => onOpenDeepDive(ticker, alert.id)}
              onOpenInfo={onOpenInfo}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
