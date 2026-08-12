/* Pulse-by-Zerodha live tab -- raw pulse items rendered in the SAME
   pictorial storycard format as the main feed (image plate + serif
   headline + gist), one full-viewport snap slot per story, newest
   first, refreshed every 60s. Deliberately upstream of the whole
   intelligence pipeline: no analysis, no measurement, no LLM of any
   kind behind this view -- a plain DB read. */
import { useEffect, useState } from 'react';
import { categoryArtUrl } from '../v3/categoryArt';

type PulseItem = {
  id: number;
  title: string;
  url: string;
  summary: string;
  published_at: string | null;
  image_url: string | null;
};

const IST_TIME = new Intl.DateTimeFormat('en-IN', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: 'Asia/Kolkata',
});

/* Same fallback chain as the feed's Plate: the story's own scraped
   photo, then curated category artwork, then nothing -- a broken-image
   glyph must never reach the page. Raw pulse items carry no category,
   so the artwork falls back to the market-commentary plate. */
function PulsePlate({ src }: { src: string | null }) {
  const [stage, setStage] = useState<'story' | 'category' | 'none'>(src !== null ? 'story' : 'category');
  const resolved = stage === 'story' ? src : stage === 'category' ? categoryArtUrl('market_commentary') : null;
  if (resolved === null) return null;
  return (
    <img
      key={resolved}
      className="lplate"
      src={resolved}
      alt=""
      loading="lazy"
      onError={() => setStage(stage === 'story' ? 'category' : 'none')}
    />
  );
}

const IST_DAY = new Intl.DateTimeFormat('en-IN', {
  weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Asia/Kolkata',
});

export default function PulseLiveV4({
  date = null,
  onCount,
  onBackToLatest,
}: {
  // null = the latest day with items ("today's paper"); YYYY-MM-DD = a
  // back day picked from the archive's pulse-wire list.
  date?: string | null;
  // Reports the loaded wire's item count up to the shell's ticker.
  onCount?: (count: number | null) => void;
  onBackToLatest?: () => void;
}) {
  const [items, setItems] = useState<PulseItem[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    setItems(null);
    onCount?.(null);
    const load = () =>
      fetch(`/api/pulse-live?limit=200${date ? `&date=${date}` : ''}`)
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((data: PulseItem[]) => {
          if (alive) {
            setItems(data);
            setError(false);
            onCount?.(data.length);
          }
        })
        .catch(() => alive && setError(true));
    load();
    // A back day never changes -- only the live (latest) day re-polls.
    const timer = date === null ? window.setInterval(load, 60_000) : null;
    return () => {
      alive = false;
      if (timer !== null) window.clearInterval(timer);
    };
  }, [date]);

  if (error && items === null) {
    return <p className="empty4">Pulse wire unavailable — retrying every minute.</p>;
  }
  if (items !== null && items.length === 0) {
    return <p className="empty4">No pulse items ingested yet today.</p>;
  }

  return (
    <div>
      {date !== null && (
        <div className="pulseback">
          <span>{IST_DAY.format(new Date(`${date}T12:00:00`))}</span>
          {onBackToLatest && (
            <button onClick={onBackToLatest}>Latest wire →</button>
          )}
        </div>
      )}
      {(items ?? []).map((item, index) => (
        <div key={item.id}>
          <a
            className={`storycard ${index === 0 ? 'first' : ''}`}
            data-testid={`v4pulse-${item.id}`}
            href={item.url}
            target="_blank"
            rel="noreferrer"
            style={{ textDecoration: 'none', color: 'inherit' }}
          >
            <div>
              <h1>{item.title}</h1>
              {item.published_at && (
                <div className="ptime4">{IST_TIME.format(new Date(item.published_at))} IST</div>
              )}
              {item.summary && <p className="lgist">{item.summary}</p>}
            </div>
            <PulsePlate src={item.image_url} />
          </a>
        </div>
      ))}
    </div>
  );
}
