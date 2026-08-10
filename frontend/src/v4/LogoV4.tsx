/* Company logo for the broadsheet UI. Resolution (candidate chain,
   transparent-placeholder probe, per-ticker cache) lives in
   logoResolve.ts and is shared with the SVG charts, so a company shows
   the SAME mark -- or the same initials fallback -- everywhere.

   Probing is viewport-gated: a logo only starts resolving once its row
   is near the viewport. The Directory mounts 2000+ rows at once and
   probing them all -- even through the resolver's concurrency window --
   blows Brandfetch's rate limit into 429s. */
import { useEffect, useRef, useState } from 'react';
import { useLogo } from './logoResolve';

function initials(ticker: string): string {
  return ticker.split('.')[0].slice(0, 2).toUpperCase();
}

export default function LogoV4({
  logoUrl,
  ticker,
  name,
  size = 'sm',
}: {
  logoUrl?: string | null;
  ticker: string;
  name?: string;
  size?: 'sm' | 'md';
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [nearViewport, setNearViewport] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (el === null || nearViewport) return;
    if (typeof IntersectionObserver === 'undefined') {
      // Test/old-browser fallback: probe immediately, as before.
      setNearViewport(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setNearViewport(true);
      },
      { rootMargin: '300px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [nearViewport]);

  const resolved = useLogo(logoUrl, ticker, name, nearViewport);
  const showFallback = resolved === null;
  return (
    <span
      ref={ref}
      className={`clg clg-${size} ${showFallback ? 'clg-fb' : ''}`}
      data-testid={`v4logo-${ticker}`}
    >
      {showFallback ? (
        <span aria-hidden="true">{initials(ticker)}</span>
      ) : resolved !== undefined ? (
        <img src={resolved} alt="" loading="lazy" />
      ) : null}
    </span>
  );
}
