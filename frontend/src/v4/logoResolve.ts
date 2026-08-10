/* Single source of truth for company logo resolution -- used by the
   HTML LogoV4 component AND every SVG chart, so a company either shows
   its real mark everywhere or its initials everywhere, never a mix.

   Chain per ticker (cached for the session): the backend's logo_url,
   then a verified ticker-keyed domain, then the group-brand domain.
   Each candidate is actually LOADED and probed on an 8x8 canvas,
   because Brandfetch answers "no logo" with HTTP 200 and a fully
   transparent image. First candidate with visible pixels wins; none ->
   null (renderers fall back to initials). */

const GROUP_DOMAINS: Record<string, string> = {
  vedanta: 'vedantalimited.com',
};

const TICKER_DOMAINS: Record<string, string> = {
  'HPCL.NS': 'hindustanpetroleum.com',
  'OILINDIA.NS': 'oil-india.com',
  'PRABHA.NS': 'prabhaenergy.com',
  'ANTELOPUS.NS': 'antelopusenergy.com',
};

export function logoCandidates(
  logoUrl: string | null | undefined,
  name: string | undefined,
  ticker: string,
): string[] {
  const urls = logoUrl ? [logoUrl] : [];
  const clientId = logoUrl?.match(/[?&]c=([^&]+)/)?.[1];
  const groupKey = name?.split(/\s+/)[0]?.toLowerCase() ?? '';
  for (const domain of [TICKER_DOMAINS[ticker], GROUP_DOMAINS[groupKey]]) {
    if (!domain) continue;
    if (clientId) urls.push(`https://cdn.brandfetch.io/${domain}?c=${clientId}`);
    // Curated-domain last resort: the site's own favicon via Google's
    // resolver -- real marks Brandfetch doesn't carry (verified for the
    // domains listed above). Only for curated domains, so the generic
    // gray-globe default can't leak in for arbitrary companies.
    urls.push(`https://www.google.com/s2/favicons?domain=${domain}&sz=128`);
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
    // CORS/canvas failure: never punish a possibly-real logo.
    return false;
  }
}

/* 'none' = the CDN answered and there is verifiably no logo (cacheable);
   'error' = the load failed (network, 429 rate limit) -- NOT proof the
   logo doesn't exist, so it must never be cached as "no logo". */
type ProbeResult = { status: 'ok'; url: string } | { status: 'none' } | { status: 'error' };

function tryLoad(url: string): Promise<ProbeResult> {
  return new Promise((resolve) => {
    const img = new Image();
    // Only Brandfetch needs the transparent-placeholder canvas probe
    // (and serves CORS headers for it). Google's favicon endpoint sends
    // NO CORS headers -- crossOrigin=anonymous makes the browser refuse
    // the image outright, so load it plain; it never serves blanks.
    const needsProbe = url.includes('cdn.brandfetch.io');
    if (needsProbe) img.crossOrigin = 'anonymous';
    img.onload = () =>
      resolve(needsProbe && isFullyTransparent(img) ? { status: 'none' } : { status: 'ok', url });
    img.onerror = () => resolve({ status: 'error' });
    img.src = url;
  });
}

/* A whole-universe list (Directory sections include ~500 global names)
   mounting at once used to fire one probe per row simultaneously --
   Brandfetch answered the burst with 429s, and every 429 was then cached
   as "no logo" for the session. Gate the probes through a small
   concurrency window instead: the queue drains in the background and no
   burst ever reaches the CDN. */
const MAX_CONCURRENT_PROBES = 4;
let activeProbes = 0;
const probeQueue: (() => void)[] = [];

function acquireProbeSlot(): Promise<void> {
  return new Promise((resolve) => {
    if (activeProbes < MAX_CONCURRENT_PROBES) {
      activeProbes += 1;
      resolve();
    } else {
      probeQueue.push(() => {
        activeProbes += 1;
        resolve();
      });
    }
  });
}

function releaseProbeSlot(): void {
  activeProbes -= 1;
  probeQueue.shift()?.();
}

const cache = new Map<string, Promise<string | null>>();

export function resolveLogo(
  logoUrl: string | null | undefined,
  ticker: string,
  name?: string,
): Promise<string | null> {
  const existing = cache.get(ticker);
  if (existing) return existing;
  const promise = (async () => {
    await acquireProbeSlot();
    try {
      let sawError = false;
      for (const url of logoCandidates(logoUrl, name, ticker)) {
        const result = await tryLoad(url);
        if (result.status === 'ok') return result.url;
        if (result.status === 'error') sawError = true;
      }
      // Every candidate failed to LOAD (vs. answered "no logo"): drop the
      // cache entry so the next mount retries once the rate limit clears.
      if (sawError) cache.delete(ticker);
      return null;
    } finally {
      releaseProbeSlot();
    }
  })();
  cache.set(ticker, promise);
  return promise;
}

import { useEffect, useState } from 'react';

/* undefined = still resolving, null = no real mark exists, string = the
   verified logo URL. `enabled=false` defers resolution entirely -- the
   Directory renders 2000+ rows and even throttled probes for all of them
   exceed Brandfetch's rate window, so offscreen rows must not probe at
   all (LogoV4 flips this on via IntersectionObserver). */
export function useLogo(
  logoUrl: string | null | undefined,
  ticker: string,
  name?: string,
  enabled: boolean = true,
): string | null | undefined {
  const [resolved, setResolved] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setResolved(undefined);
    resolveLogo(logoUrl, ticker, name).then((url) => {
      if (!cancelled) setResolved(url);
    });
    return () => {
      cancelled = true;
    };
  }, [logoUrl, ticker, name, enabled]);
  return resolved;
}
