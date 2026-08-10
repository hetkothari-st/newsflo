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

export default function PulseLiveV4() {
  const [items, setItems] = useState<PulseItem[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch('/api/pulse-live?limit=80')
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((data: PulseItem[]) => {
          if (alive) {
            setItems(data);
            setError(false);
          }
        })
        .catch(() => alive && setError(true));
    load();
    const timer = window.setInterval(load, 60_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  if (error && items === null) {
    return <p className="empty4">Pulse wire unavailable — retrying every minute.</p>;
  }
  if (items !== null && items.length === 0) {
    return <p className="empty4">No pulse items ingested yet today.</p>;
  }

  return (
    <div>
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
              <div className="lmove">
                PULSE · {item.published_at ? IST_TIME.format(new Date(item.published_at)) + ' IST' : 'LIVE'}
              </div>
              <h1>{item.title}</h1>
              {item.summary && <p className="lgist">{item.summary}</p>}
            </div>
            <PulsePlate src={item.image_url} />
          </a>
        </div>
      ))}
    </div>
  );
}
