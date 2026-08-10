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
export function formatMarketCap(rupees: number): string {
  const crore = rupees / 1e7;
  if (crore >= 1e5) {
    const lakhCrore = crore / 1e5;
    return `₹${lakhCrore.toFixed(lakhCrore >= 10 ? 1 : 2)}L Cr`;
  }
  return `₹${crore.toLocaleString('en-IN', { maximumFractionDigits: crore >= 100 ? 0 : 1 })} Cr`;
}
