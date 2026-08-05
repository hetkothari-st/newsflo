/* v4 broadsheet feed: the day's measured stories as a newspaper front
   page. Lead story gets the hero treatment (giant serif headline +
   halftone plate); the rest run as ruled editorial rows. Expanding a
   story unfolds a full-bleed ink band -- "THE RIPPLE" stamped in
   condensed caps -- with the affected companies as ruled text rows and
   the timeline beneath. Data comes from the same feed-v2 endpoints as
   the v3 shell; filter semantics (cap_tiers story match + row-level
   narrowing) are identical. */
import { useCallback, useEffect, useState } from 'react';
import {
  getAlertDetail,
  getCalendarCounts,
  getFeedAlerts,
  type AlertDetail,
  type CapTier,
  type FeedAlert,
  type RippleLayer,
} from '../v3/api';
import { useAuth } from '../lib/auth';

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

function RippleBand({
  alert,
  detail,
  capFilter,
  onClose,
  onOpenDeepDive,
}: {
  alert: FeedAlert;
  detail: AlertDetail | null;
  capFilter: CapTier | 'ALL';
  onClose: () => void;
  onOpenDeepDive: (ticker: string, alertId?: number) => void;
}) {
  const visibleRows = (layer: RippleLayer) =>
    capFilter === 'ALL' ? layer.rows : layer.rows.filter((row) => row.cap_tier === capFilter);
  const anyRows = detail !== null && detail.layers.some((layer) => visibleRows(layer).length > 0);
  return (
    <div className="band">
      <div className="stamp">The Ripple</div>
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
            <p className="ltitle">{layer.title}</p>
            {layer.note !== null && <p className="lnote4">{layer.note}</p>}
            {rows.map((row) => (
              <div
                className="crow"
                key={row.ticker}
                data-testid={`v4row-${row.ticker}`}
                onClick={() => onOpenDeepDive(row.ticker, alert.id)}
              >
                <span className="tk4">{row.ticker}</span>
                <span className="nm4">{row.name}</span>
                {row.cap_tier !== null && <span className="cap4">{row.cap_tier}</span>}
                {row.is_exposure_only || row.excess_move_pct == null ? (
                  <span className="mv4">exposure</span>
                ) : (
                  <span className={`mv4 ${moveClass(row.excess_move_pct)}`}>
                    {fmtPct(row.excess_move_pct)}
                  </span>
                )}
              </div>
            ))}
          </div>
        );
      })}
      {detail !== null && detail.timeline.length > 0 && (
        <div className="tl4">
          {detail.timeline.map((entry, index) => (
            <div className="tlrow4" key={`${entry.horizon}-${index}`}>
              <p className="tlh4">{entry.horizon.replace(/_/g, ' ')}</p>
              <p className="tld4">{entry.description}</p>
            </div>
          ))}
        </div>
      )}
      <button className="close4" onClick={onClose}>
        Fold it closed ↑
      </button>
    </div>
  );
}

export default function FeedV4({
  capFilter,
  date,
  onEdition,
  onOpenDeepDive,
}: {
  capFilter: CapTier | 'ALL';
  // null = today (with latest-edition fallback); YYYY-MM-DD = a back
  // issue picked from the archive, fetched exactly, no fallback.
  date: string | null;
  onEdition: (edition: { count: number; date: string | null }) => void;
  onOpenDeepDive: (ticker: string, alertId?: number) => void;
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
  }, [token, date, onEdition]);

  const toggle = useCallback(
    (alertId: number) => {
      setOpenId((current) => (current === alertId ? null : alertId));
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
    [token],
  );

  // Same story-level filter the v3 shell ships: a story matches when ANY
  // tagged company sits in the chosen tier.
  const visible = (alerts ?? []).filter(
    (alert) =>
      capFilter === 'ALL' ||
      (alert.cap_tiers ? alert.cap_tiers.includes(capFilter) : alert.peak_cap_tier === capFilter),
  );

  if (error !== null) return <p className="empty4">{error}</p>;
  if (alerts !== null && alerts.length === 0)
    return <p className="empty4">No measured stories yet today. New editions appear as the market reacts.</p>;
  if (alerts !== null && visible.length === 0)
    return <p className="empty4">No stories in this cap tier today. Tap “All” for the full edition.</p>;

  const [lead, ...rest] = visible;

  return (
    <div>
      {lead && (
        <>
          <div className="lead">
            <div>
              <div className={`lmove ${moveClass(lead.excess_move_pct)}`}>
                {lead.excess_move_pct < 0 ? '▼' : '▲'} {Math.abs(lead.excess_move_pct).toFixed(1)}%
              </div>
              <h1 onClick={() => toggle(lead.id)}>{lead.article.title}</h1>
              <p className="lgist">{lead.summary_short ?? lead.summary_long ?? ''}</p>
              <MetaLine alert={lead} onToggle={() => toggle(lead.id)} />
            </div>
            {lead.article.image_url !== null && (
              <img className="lplate" src={lead.article.image_url} alt="" loading="lazy" />
            )}
          </div>
          {openId === lead.id && (
            <RippleBand
              alert={lead}
              detail={details[lead.id] ?? null}
              capFilter={capFilter}
              onClose={() => setOpenId(null)}
              onOpenDeepDive={onOpenDeepDive}
            />
          )}
          <hr className="rule" />
        </>
      )}
      {rest.map((alert, index) => (
        <div key={alert.id}>
          {index > 0 && <hr className="rule-hair" />}
          <div className="story" onClick={() => toggle(alert.id)} data-testid={`v4story-${alert.id}`}>
            <div className="srow4">
              <h2>{alert.article.title}</h2>
              <span className={`smove ${moveClass(alert.excess_move_pct)}`}>
                {alert.excess_move_pct < 0 ? '▼' : '▲'} {Math.abs(alert.excess_move_pct).toFixed(1)}%
              </span>
            </div>
            <MetaLine alert={alert} onToggle={() => toggle(alert.id)} />
          </div>
          {openId === alert.id && (
            <RippleBand
              alert={alert}
              detail={details[alert.id] ?? null}
              capFilter={capFilter}
              onClose={() => setOpenId(null)}
              onOpenDeepDive={onOpenDeepDive}
            />
          )}
        </div>
      ))}
    </div>
  );
}
