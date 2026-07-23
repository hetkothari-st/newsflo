export interface FeedV2Article {
  id: number;
  title: string;
  url: string;
  source: string;
  published_at: string | null;
}

export interface IntensityComponent {
  label: string;
  raw: number;
  weight: number;
  contribution: number;
}

export interface Intensity {
  score: number;
  band: 'High' | 'Moderate' | 'Low';
  components: IntensityComponent[];
}

export type Verdict = 'COMPANY_SPECIFIC' | 'SECTOR_WIDE' | 'UNCONFIRMED';

export type RippleRelationship =
  | 'BENEFICIARY'
  | 'CUSTOMER_INPUT_COST'
  | 'SUPPLIER'
  | 'SUBSTITUTE'
  | 'COMPETITOR'
  | 'SECTOR_WIDE';

export interface RippleCompany {
  ticker: string;
  name: string;
  relationship: RippleRelationship;
  direction: 'bullish' | 'bearish';
  excess_move_pct: number | null;
  intensity: Intensity | null;
  is_exposure_only: boolean;
  in_my_holdings: boolean;
}

export type TimelineHorizon = 'TODAY' | 'DAYS' | 'WEEKS' | 'MONTHS' | 'QUARTERS';

export interface TimelineEntry {
  horizon: TimelineHorizon;
  description: string;
}

export interface FeedV2Alert {
  id: number;
  category: string;
  created_at: string;
  summary_short: string | null;
  summary_long: string | null;
  article: FeedV2Article;
  excess_move_pct: number;
  direction: 'bullish' | 'bearish';
  raw_move_pct: number;
  sector_move_pct: number;
  volume_multiple: number | null;
  benchmark_ticker: string;
  is_fallback_benchmark: boolean;
  peak_ticker: string;
  peak_company_name: string;
  verdict: Verdict;
  intensity: Intensity;
  breadth_score: number;
  in_my_holdings: boolean;
  ripple?: RippleCompany[];
  timeline?: TimelineEntry[];
}

function authHeaders(token: string | null): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

interface ApiError {
  detail?: string;
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as ApiError;
    if (typeof body.detail === 'string') return body.detail;
    return `Request failed (${res.status})`;
  } catch {
    return `Request failed (${res.status})`;
  }
}

export async function getFeedV2Alerts(token: string | null = null): Promise<FeedV2Alert[]> {
  const res = await fetch('/api/feed-v2', { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as FeedV2Alert[];
}

export async function getFeedV2Alert(id: number, token: string | null = null): Promise<FeedV2Alert> {
  const res = await fetch(`/api/feed-v2/${id}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as FeedV2Alert;
}
