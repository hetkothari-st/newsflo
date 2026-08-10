/* Directory live-cap overlay: API client + formatter, deliberately its
   own module (not v3/api.ts, which three surfaces share) so the feature
   stays isolated and merge-friendly. */

export type CapSource = 'live' | 'stored';

export interface LiveCapRow {
  ticker: string;
  rank: number;
  market_cap: number; // absolute rupees
  cap_source: CapSource;
  as_of: string | null;
}

export async function getDirectoryLiveCaps(): Promise<LiveCapRow[]> {
  const res = await fetch('/api/feed-v2/directory/live-caps');
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return (await res.json()) as LiveCapRow[];
}

/* Indian-numbering crore formatting: ₹17.9L Cr for lakh-crore scale,
   ₹9,420 Cr below it, one decimal only when the number is small enough
   for it to matter. */
/* Global (non-Indian) rows store market_cap in USD -- a different unit
   in the same column, distinguished by market/index_tier. Formatted in
   the $T/$B idiom those numbers are read in, never crore. */
export function formatMarketCapUsd(usd: number): string {
  if (usd >= 1e12) return `$${(usd / 1e12).toFixed(2)}T`;
  if (usd >= 1e9) return `$${(usd / 1e9).toFixed(usd >= 1e11 ? 0 : 1)}B`;
  if (usd >= 1e6) return `$${(usd / 1e6).toFixed(0)}M`;
  return `$${usd.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
}

export function formatMarketCap(rupees: number): string {
  const crore = rupees / 1e7;
  if (crore >= 1e5) {
    const lakhCrore = crore / 1e5;
    return `₹${lakhCrore.toFixed(lakhCrore >= 10 ? 1 : 2)}L Cr`;
  }
  return `₹${crore.toLocaleString('en-IN', { maximumFractionDigits: crore >= 100 ? 0 : 1 })} Cr`;
}
