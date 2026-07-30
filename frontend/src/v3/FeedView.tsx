/* The vertical card feed (spec v2 §2, §7): card front = skim layer
   (excess move, verdict, headline, gist, meta, "see who's affected"),
   card back = layered ripple + timeline behind mini-tabs. Swipe left
   flips front->back, swipe right flips back; vertical scroll moves
   through stories; taps mirror the swipes on non-touch devices --
   ported from the approved prototype. */
import { useCallback, useEffect, useRef, useState } from 'react';
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
  VERDICT_LABELS,
  verdictClass,
} from './format';
import { useAuth } from '../lib/auth';

function LayerBlock({
  layer,
  onOpenDeepDive,
  onOpenInfo,
}: {
  layer: RippleLayer;
  onOpenDeepDive: (ticker: string) => void;
  onOpenInfo: (row: LayerRow) => void;
}) {
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
      {layer.rows.map((row) => (
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
    <div className="nimg">
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
  onFlip,
  onUnflip,
  onOpenDeepDive,
  onOpenInfo,
}: {
  alert: FeedAlert;
  flipped: boolean;
  detail: AlertDetail | null;
  onFlip: () => void;
  onUnflip: () => void;
  onOpenDeepDive: (ticker: string) => void;
  onOpenInfo: (row: LayerRow) => void;
}) {
  const [backTab, setBackTab] = useState<'ripple' | 'timeline'>('ripple');
  const [imageFailed, setImageFailed] = useState(false);
  const dir = moveDir(alert.excess_move_pct, alert.verdict);
  const showImage = alert.article.image_url !== null && !imageFailed;
  return (
    <div className={`card ${flipped ? 'flipped' : ''}`} data-card={alert.id}>
      <div className="flip">
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
              <div className="xlabel">excess vs sector</div>
            </div>
            <span className={`verdict ${verdictClass(alert.verdict)}`}>
              {VERDICT_LABELS[alert.verdict]}
            </span>
          </div>
          <div className="headline">{alert.article.title}</div>
          <div className="gist">{alert.summary_short ?? alert.summary_long ?? ''}</div>
          {showImage && (
            <NewsImage src={alert.article.image_url!} onFail={() => setImageFailed(true)} />
          )}
          <div className="ffoot">
            <div className="meta">
              <span>{alert.category.replace(/_/g, ' ')}</span>
              <span>·</span>
              <span>{fmtTime(alert.created_at)}</span>
              {alert.in_my_holdings && (
                <>
                  <span className="odot" />
                  <span>held</span>
                </>
              )}
            </div>
            <div className="cta">
              <span>See who's affected</span>
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
              <div className="l">Raw</div>
              <div className="v" style={{ color: moveColor(alert.raw_move_pct) }}>
                {fmtPct(alert.raw_move_pct)}
              </div>
            </div>
            <div className="st">
              <div className="l">Sector</div>
              <div className="v" style={{ color: moveColor(alert.sector_move_pct) }}>
                {fmtPct(alert.sector_move_pct)}
              </div>
            </div>
            <div className="st">
              <div className="l">Volume</div>
              <div className="v">{fmtVolume(alert.volume_multiple)}</div>
            </div>
          </div>
          <div className="tabsmini">
            <button className={backTab === 'ripple' ? 'on' : ''} onClick={() => setBackTab('ripple')}>
              Ripple
            </button>
            <button
              className={backTab === 'timeline' ? 'on' : ''}
              onClick={() => setBackTab('timeline')}
            >
              Timeline
            </button>
          </div>
          <div className="layers">
            {detail === null ? (
              <p className="empty">Loading analysis…</p>
            ) : backTab === 'ripple' ? (
              detail.layers.map((layer) => (
                <LayerBlock
                  key={layer.relationship}
                  layer={layer}
                  onOpenDeepDive={onOpenDeepDive}
                  onOpenInfo={onOpenInfo}
                />
              ))
            ) : (
              <TimelineBlock timeline={detail.timeline} />
            )}
          </div>
          <div className="bfoot">
            Intensity measures how hard the news hit — not whether a stock is good to own.
          </div>
        </div>
      </div>
    </div>
  );
}

export default function FeedView({
  active,
  capFilter,
  onOpenDeepDive,
  onOpenInfo,
  onAnyFlip,
}: {
  active: boolean;
  capFilter: CapTier | 'ALL';
  onOpenDeepDive: (ticker: string, alertId: number) => void;
  onOpenInfo: (row: LayerRow) => void;
  onAnyFlip: () => void;
}) {
  const { token } = useAuth();
  const [alerts, setAlerts] = useState<FeedAlert[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flippedIds, setFlippedIds] = useState<Set<number>>(new Set());
  const [details, setDetails] = useState<Record<number, AlertDetail>>({});
  const feedRef = useRef<HTMLDivElement | null>(null);
  const touchStartX = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getFeedAlerts(token)
      .then((result) => {
        if (!cancelled) setAlerts(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const loadDetail = useCallback(
    (alertId: number) => {
      setDetails((current) => {
        if (current[alertId]) return current;
        getAlertDetail(alertId, token)
          .then((detail) => {
            setDetails((latest) => ({ ...latest, [alertId]: detail }));
          })
          .catch(() => {
            /* detail stays absent; the back shows its loading state */
          });
        return current;
      });
    },
    [token],
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

  const isVisible = useCallback(
    (alert: FeedAlert): boolean => {
      if (capFilter === 'ALL') return true;
      const detail = details[alert.id];
      if (detail) {
        return detail.layers.some((layer) => layer.rows.some((row) => row.cap_tier === capFilter));
      }
      return alert.peak_cap_tier === capFilter;
    },
    [capFilter, details],
  );

  return (
    <div className={`view ${active ? 'on' : ''}`}>
      <div className="feed" ref={feedRef}>
        {error !== null && <p className="empty">{error}</p>}
        {alerts !== null && alerts.length === 0 && (
          <p className="empty">No measured stories yet today. New alerts appear as the market reacts.</p>
        )}
        {alerts?.map(
          (alert) =>
            isVisible(alert) && (
              <div className="slot" key={alert.id}>
                <Card
                  alert={alert}
                  flipped={flippedIds.has(alert.id)}
                  detail={details[alert.id] ?? null}
                  onFlip={() => flip(alert.id)}
                  onUnflip={() => unflip(alert.id)}
                  onOpenDeepDive={(ticker) => onOpenDeepDive(ticker, alert.id)}
                  onOpenInfo={onOpenInfo}
                />
              </div>
            ),
        )}
      </div>
    </div>
  );
}
