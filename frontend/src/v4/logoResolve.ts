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

function tryLoad(url: string): Promise<string | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(isFullyTransparent(img) ? null : url);
    img.onerror = () => resolve(null);
    img.src = url;
  });
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
    for (const url of logoCandidates(logoUrl, name, ticker)) {
      const ok = await tryLoad(url);
      if (ok !== null) return ok;
    }
    return null;
  })();
  cache.set(ticker, promise);
  return promise;
}

import { useEffect, useState } from 'react';

/* undefined = still resolving, null = no real mark exists, string = the
   verified logo URL. */
export function useLogo(
  logoUrl: string | null | undefined,
  ticker: string,
  name?: string,
): string | null | undefined {
  const [resolved, setResolved] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    let cancelled = false;
    setResolved(undefined);
    resolveLogo(logoUrl, ticker, name).then((url) => {
      if (!cancelled) setResolved(url);
    });
    return () => {
      cancelled = true;
    };
  }, [logoUrl, ticker, name]);
  return resolved;
}
