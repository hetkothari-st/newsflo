/* API client for the card-feed UI (docs/NEWS_IMPACT_APP_SPEC_V2.md).
   Fresh module for the v3 surface -- the old lib/feedV2Api.ts stays for
   the retired feed-v2 components until they are deleted. */
import type { Fundamentals } from '../lib/api';

export type CapTier = 'LARGE' | 'MID' | 'SMALL' | 'MICRO';
export type LiquidityTier = 'LOW' | 'MODERATE' | 'HIGH';
export type Verdict = 'COMPANY_SPECIFIC' | 'SECTOR_WIDE' | 'UNCONFIRMED';
export type Direction = 'bullish' | 'bearish';

export interface IntensityComponent {
  label: string;
  raw: number;
  score: number;
  weight: number;
  contribution: number;
}

export interface Intensity {
  score: number;
  band: 'High' | 'Moderate' | 'Low';
  components: IntensityComponent[];
}

export interface FeedArticle {
  id: number;
  image_url: string | null;
  title: string;
  url: string;
  source: string;
  published_at: string | null;
}

export interface FeedAlert {
  id: number;
  category: string;
  // Server-translated category chip label for the active language; null
  // for English / untranslated (frontend prettifies the slug).
  category_label: string | null;
  created_at: string;
  summary_short: string | null;
  summary_long: string | null;
  article: FeedArticle;
  excess_move_pct: number;
  direction: Direction;
  raw_move_pct: number;
  sector_move_pct: number;
  volume_multiple: number | null;
  benchmark_ticker: string;
  is_fallback_benchmark: boolean;
  peak_ticker: string;
  peak_company_name: string;
  peak_cap_tier: CapTier | null;
  // Distinct tiers across ALL tagged companies -- drives the top-bar cap
  // filter (a story matches when any affected company sits in the tier).
  cap_tiers: CapTier[];
  verdict: Verdict;
  intensity: Intensity;
  breadth_score: number;
  in_my_holdings: boolean;
}

export interface LayerRow {
  ticker: string;
  name: string;
  sector: string;
  cap_tier: CapTier | null;
  liquidity_tier: LiquidityTier | null;
  delivery_pct: number | null;
  // Sourced description. Non-null ONLY when it can be attributed -- the
  // backend withholds the legacy LLM-invented text (app.companies.
  // descriptions.sourced_description). The URL is the CC BY-SA
  // attribution and must be rendered wherever the text is.
  business_desc: string | null;
  business_desc_source_url?: string | null;
  // Sent by app.market.ripple_layers.compute_ripple_layers (backs
  // AlertDetail.layers[].rows) and app.market.ripple.get_sector_peers_for_alert
  // (backs StockDeepDive.peers below) -- both already emit it (Task 7).
  fundamentals?: Fundamentals | null;
  direction: Direction;
  excess_move_pct: number | null;
  intensity: Intensity | null;
  is_exposure_only: boolean;
  in_my_holdings: boolean;
  why: string | null;
  logo_url: string | null;
}

export interface RippleLayer {
  title: string;
  relationship: string;
  icon: 'win' | 'lose' | 'side';
  note: string | null;
  rows: LayerRow[];
}

export type TimelineHorizon = 'TODAY' | 'DAYS' | 'WEEKS' | 'MONTHS' | 'QUARTERS';

export interface TimelineEntry {
  horizon: TimelineHorizon;
  description: string;
}

export interface AlertDetail extends FeedAlert {
  layers: RippleLayer[];
  timeline: TimelineEntry[];
}

export interface StockDeepDive {
  ticker: string;
  name: string;
  sector: string;
  cap_tier: CapTier | null;
  // Sourced description. Non-null ONLY when it can be attributed -- the
  // backend withholds the legacy LLM-invented text (app.companies.
  // descriptions.sourced_description). The URL is the CC BY-SA
  // attribution and must be rendered wherever the text is.
  business_desc: string | null;
  business_desc_source_url?: string | null;
  // Sent by app.routers.stock_deep_dive._company_facts, which already
  // calls fundamentals_payload(company) (Task 7).
  fundamentals?: Fundamentals | null;
  logo_url: string | null;
  market_cap: number | null;
  pe: number | null;
  in_my_holdings: boolean;
  excess_move_pct: number | null;
  raw_move_pct: number | null;
  sector_move_pct: number | null;
  volume_multiple: number | null;
  liquidity_tier: LiquidityTier | null;
  delivery_pct: number | null;
  intensity: Intensity | null;
  is_exposure_only: boolean | null;
  // Per-story reasoning (alert context only): why this company sits in
  // its card-back section for this news.
  why: string | null;
  rationale: string | null;
  section_title: string | null;
  peers: LayerRow[];
}

export interface DiscoveryEntry {
  ticker: string;
  name: string;
  sector: string;
  cap_tier: CapTier | null;
  liquidity_tier: LiquidityTier | null;
  excess_move_pct: number | null;
  volume_multiple: number | null;
  delivery_pct: number | null;
  materiality: number | null;
  why: string | null;
  alert_id: number;
  headline: string;
  via_ticker: string | null;
  logo_url: string | null;
  low_delivery: boolean;
  thin_trading: boolean;
}

export type DiscoveryTab = 'materiality' | 'holdings' | 'unusual';

export interface DirectoryCompany {
  ticker: string;
  name: string;
  sector: string;
  cap_tier: CapTier | null;
  logo_url: string | null;
}

export interface PortfolioHolding {
  ticker: string;
  name: string;
  quantity: number;
  logo_url: string | null;
  affected_alert_id: number | null;
  affected_headline: string | null;
}

export interface PortfolioOverlay {
  holdings: PortfolioHolding[];
  affected_count: number;
}

export type CarOutcomeLabel = 'HELD' | 'REVERSED' | 'FLAT';

export interface CarReviewRow {
  id: number;
  ticker: string;
  company_name: string;
  category: string;
  article_title: string;
  article_url: string;
  alert_created_at: string;
  day0_excess_move_pct: number;
  car_pct: number;
  car_series: number[] | null;
  outcome_label: CarOutcomeLabel;
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

async function getJson<T>(url: string, token: string | null): Promise<T> {
  const res = await fetch(url, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as T;
}

export function getFeedAlerts(
  token: string | null = null,
  options: { lang?: string; date?: string } = {},
): Promise<FeedAlert[]> {
  const params = new URLSearchParams();
  if (options.lang && options.lang !== 'en') params.set('lang', options.lang);
  if (options.date) params.set('date', options.date);
  const query = params.toString() ? `?${params.toString()}` : '';
  return getJson<FeedAlert[]>(`/api/feed-v2${query}`, token);
}

export function getAlertDetail(
  id: number,
  token: string | null = null,
  lang?: string,
): Promise<AlertDetail> {
  const query = lang && lang !== 'en' ? `?lang=${lang}` : '';
  return getJson<AlertDetail>(`/api/feed-v2/${id}${query}`, token);
}

export type CalendarCounts = Record<string, number>;

export function getCalendarCounts(year: number, month: number): Promise<CalendarCounts> {
  return getJson<CalendarCounts>(`/api/calendar/counts?year=${year}&month=${month}`, null);
}

export function getStockDeepDive(
  ticker: string,
  alertId?: number,
  token: string | null = null,
  lang?: string,
): Promise<StockDeepDive> {
  const params = new URLSearchParams();
  if (alertId !== undefined) params.set('alert_id', String(alertId));
  if (lang && lang !== 'en') params.set('lang', lang);
  const query = params.toString() ? `?${params.toString()}` : '';
  return getJson<StockDeepDive>(`/api/feed-v2/stock/${encodeURIComponent(ticker)}${query}`, token);
}

export function getDiscovery(tab: DiscoveryTab, token: string | null = null): Promise<DiscoveryEntry[]> {
  return getJson<DiscoveryEntry[]>(`/api/feed-v2/discovery/${tab}`, token);
}

export function getDirectory(
  filters: { capTier?: CapTier; sector?: string } = {},
  token: string | null = null,
): Promise<DirectoryCompany[]> {
  const params = new URLSearchParams();
  if (filters.capTier) params.set('cap_tier', filters.capTier);
  if (filters.sector) params.set('sector', filters.sector);
  const query = params.toString() ? `?${params.toString()}` : '';
  return getJson<DirectoryCompany[]>(`/api/feed-v2/directory${query}`, token);
}

export function getPortfolioOverlay(token: string | null): Promise<PortfolioOverlay> {
  return getJson<PortfolioOverlay>('/api/feed-v2/portfolio', token);
}

export function getCarReview(token: string | null): Promise<CarReviewRow[]> {
  return getJson<CarReviewRow[]>('/api/car-review', token);
}
