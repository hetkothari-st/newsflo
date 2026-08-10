/* Raw Pulse-by-Zerodha wire -- every pulse item exactly as ingested,
   newest first, refreshed every 60s. Deliberately upstream of the whole
   intelligence pipeline: no analysis, no measurement gating, no LLM of
   any kind behind this view. Editorial list styling per the broadsheet
   spec: hairline rules, mono timestamps, no emoji. */
import { useEffect, useState } from 'react';

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

  return (
    <section className="pulsewire" aria-label="Pulse live wire">
      <div className="pulsehead">
        <span>PULSE — LIVE WIRE</span>
        <span>AGGREGATED BY ZERODHA PULSE · UNANALYZED · NEWEST FIRST</span>
      </div>
      {error && <p className="pulseempty">Wire unavailable — retrying every minute.</p>}
      {items !== null && items.length === 0 && !error && (
        <p className="pulseempty">No pulse items ingested yet today.</p>
      )}
      {(items ?? []).map((item) => (
        <a key={item.id} className="pulserow" href={item.url} target="_blank" rel="noreferrer">
          {item.image_url ? (
            <img className="pulseimg" src={item.image_url} alt="" loading="lazy" />
          ) : (
            <div className="pulseimg pulseimg-none" aria-hidden="true">
              N
            </div>
          )}
          <div className="pulsebody">
            <div className="pulsetime">
              {item.published_at ? IST_TIME.format(new Date(item.published_at)) + ' IST' : '—'}
            </div>
            <div className="pulsetitle">{item.title}</div>
            {item.summary && <div className="pulsesumm">{item.summary}</div>}
          </div>
        </a>
      ))}
    </section>
  );
}
