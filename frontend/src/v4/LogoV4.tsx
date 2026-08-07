/* Company logo for the broadsheet UI: the same Brandfetch art the
   deployed shell uses (row.logo_url from the backend). Falls back to
   ink-on-paper ticker initials -- a company without logo art must still
   read as a real company, never a broken image or a blank gap.

   Two quirks handled here:
   - Brandfetch answers "no logo exists" with HTTP 200 and a fully
     TRANSPARENT placeholder (onError never fires), so onLoad runs an
     8x8 canvas probe; an all-transparent image counts as a miss. CORS
     is open on their CDN ('*'), so the probe uses crossOrigin; any
     canvas failure keeps the image (never punish a real logo).
   - Some listed group subsidiaries (e.g. Vedanta Oil and Gas) have no
     art under their own ISIN/ticker, but the GROUP mark exists under
     the group's domain. A small explicit map tries that before giving
     up -- the group mark is the subsidiary's real branding, not a
     guess. Extend the map only for unambiguous group names. */
import { useEffect, useState } from 'react';

const GROUP_DOMAINS: Record<string, string> = {
  vedanta: 'vedantalimited.com',
};

/* Ticker-keyed domains for companies whose own ISIN/ticker has no
   Brandfetch art but whose website does. Verified real marks -- extend
   only after checking the domain actually serves one. */
const TICKER_DOMAINS: Record<string, string> = {
  'HPCL.NS': 'hindustanpetroleum.com',
  'OILINDIA.NS': 'oil-india.com',
};

function initials(ticker: string): string {
  return ticker.split('.')[0].slice(0, 2).toUpperCase();
}

function candidateUrls(
  logoUrl: string | null | undefined,
  name: string | undefined,
  ticker: string,
): string[] {
  const urls = logoUrl ? [logoUrl] : [];
  const clientId = logoUrl?.match(/[?&]c=([^&]+)/)?.[1];
  const groupKey = name?.split(/\s+/)[0]?.toLowerCase() ?? '';
  for (const domain of [TICKER_DOMAINS[ticker], GROUP_DOMAINS[groupKey]]) {
    if (domain && clientId) urls.push(`https://cdn.brandfetch.io/${domain}?c=${clientId}`);
  }
  return urls;
}

function isFullyTransparent(img: HTMLImageElement): boolean {
  try {
    const side = 8;
    const canvas = document.createElement('canvas');
    canvas.width = side;
    canvas.height = side;
    const ctx = canvas.getContext('2d');
    if (!ctx) return false;
    ctx.drawImage(img, 0, 0, side, side);
    const { data } = ctx.getImageData(0, 0, side, side);
    for (let i = 3; i < data.length; i += 4) {
      if (data[i] > 0) return false;
    }
    return true;
  } catch {
    return false;
  }
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
  const [candidateIndex, setCandidateIndex] = useState(0);
  useEffect(() => setCandidateIndex(0), [logoUrl, ticker]);
  const candidates = candidateUrls(logoUrl, name, ticker);
  const src = candidates[candidateIndex];
  const showFallback = src === undefined;
  return (
    <span className={`clg clg-${size} ${showFallback ? 'clg-fb' : ''}`} data-testid={`v4logo-${ticker}`}>
      {showFallback ? (
        <span aria-hidden="true">{initials(ticker)}</span>
      ) : (
        <img
          key={src}
          src={src}
          alt=""
          loading="lazy"
          crossOrigin="anonymous"
          onError={() => setCandidateIndex((index) => index + 1)}
          onLoad={(event) => {
            if (isFullyTransparent(event.currentTarget)) {
              setCandidateIndex((index) => index + 1);
            }
          }}
        />
      )}
    </span>
  );
}
