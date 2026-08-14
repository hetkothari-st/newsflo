/* API client for the card-feed UI (docs/NEWS_IMPACT_APP_SPEC_V2.md).
   Fresh module for the v3 surface -- the old lib/feedV2Api.ts stays for
   the retired feed-v2 components until they are deleted. */
import type { Fundamentals } from '../lib/api';
import type { VolatilityRangeData } from '../components/VolatilityRange';

export type CapTier = 'LARGE' | 'MID' | 'SMALL' | 'MICRO';
export type LiquidityTier = 'LOW' | 'MODERATE' | 'HIGH';
export type Verdict = 'COMPANY_SPECIFIC' | 'SECTOR_WIDE' | 'UNCONFIRMED';
// Legacy per-row label (AlertCompany.direction) -- still served on
// LayerRow for pre-gate alerts; NOT the dead-zone-classified reaction
// (that is ReactionDirection below, spec §22/§37).
export type Direction = 'bullish' | 'bearish';
// The one sanctioned excess->direction mapping (app.market.measure.
// classify_reaction): dead-zone-aware, used for FeedAlert.direction,
// market_reaction.direction and LayerRow.reaction_direction alike.
export type ReactionDirection = 'positive' | 'negative' | 'flat' | 'unknown';
// Gate-authoritative fundamental verdict (app.analysis.impact_graph.
// publication_gate.ECONOMIC_EFFECTS) -- separate truth from the price
// reaction above (spec §37/§38).
export type EconomicEffect = 'positive' | 'negative' | 'mixed' | 'uncertain' | 'no_material_impact';
export type MaterialityGrade = 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN';
// Final-blueprint §18/§19 (Task 9): app.analysis.impact_graph.
// publication_gate.confidence_band's closed vocabulary
// (CONFIDENCE_BANDS = HIGH | MEDIUM | LOW | UNKNOWN) -- the SAME closed
// set materiality_grade uses, not the pre-blueprint pipeline.band_for_score
// spelling (LOW/MODERATE/HIGH/VERY_HIGH) this type used to carry. Backend
// Task 6 rewrites the wire value to this vocabulary; band-only display,
// never a numeric confidence_score (ruling R4).
export type ConfidenceBand = 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN';
// Final-blueprint §3/§11 (Task 9): the gate's registry-level directness,
// independent of causal_distance and independent of publication_tier below
// -- a DIRECT exposure can still publish at a non-primary tier (§28
// example: "DIRECT EXPOSURE · SECONDARY").
export type CausalDirectness = 'DIRECT' | 'INDIRECT' | 'REMOTE';
// Final-blueprint §3/§29 (Task 9): the tier the gate actually published
// at. Mirrors LayerRow.display_tier's value set plus 'macro_context' --
// backend Task 6 is expected to serve this key going forward; the dead
// 'secondary_deep_dive'/'secondary' spellings are read-only legacy
// compat (never written), same as display_tier's.
export type PublicationTier =
  | 'primary'
  | 'secondary_ripple'
  | 'macro_context'
  | 'secondary_deep_dive'
  | 'secondary';
export type ImpactType = 'direct' | 'indirect';
export type MarketSensitivity = 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN';
export type ReactionSignificance = 'significant' | 'normal' | 'noise' | 'unknown';
export type DataQuality = 'ok' | 'partial_bar' | 'stale' | 'invalid';

// Independent market-reaction object (strict engine, spec §20/§22):
// dead-zone-classified direction, separate from fundamental impact.
// Always present on a strict-mode alert -- "unavailable" status with
// direction "unknown" when the price feed failed (spec §49), never
// omitted.
export interface MarketReaction {
  status: 'ok' | 'unavailable';
  direction: ReactionDirection;
  bar_complete: number | null;
  raw_move_pct: number | null;
  excess_move_pct: number | null;
  benchmark_ticker: string | null;
  benchmark_is_fallback: boolean;
  data_quality: DataQuality | null;
  session_state: string | null;
  reaction_significance: ReactionSignificance;
}

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
  // null when the strict engine serves a fundamental-only alert whose
  // price feed failed (spec §49) -- render an honest dash, never 0.
  excess_move_pct: number | null;
  // BREAKING vocab change (Task 14): this used to be a raw sign(excess)
  // -> bullish/bearish label with no dead zone. classify_reaction is the
  // one sanctioned mapping now -- same vocab as market_reaction.direction.
  direction: ReactionDirection | null;
  market_reaction?: MarketReaction | null;
  // Null on an honest-unavailable measurement (finding I5): the strict
  // engine's _unavailable_measurement (backend feed_v2.py, spec §49)
  // serves EVERY market field as null when the price feed failed, these
  // two included. They were typed non-nullable, so the v4 hero called
  // .toFixed() straight on null and the whole feed crashed on exactly the
  // payload the backend built to stay honest. Render "—", never 0.
  raw_move_pct: number | null;
  sector_move_pct: number | null;
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
  // Owner decision 2026-08-14: "primary" = headline comes from gate-proven
  // PRIMARY companies; "indirect_only" = a gated alert with zero PRIMARY,
  // headlined from its secondary/deep-dive movers (render an explicit
  // indirect-exposure badge); null/undefined = ungated legacy alert.
  exposure?: 'primary' | 'indirect_only' | null;
  // Final-blueprint §15 (Task 9): set when the article's mechanisms span
  // more than one sector (direct + indirect + macro all present) -- the
  // indirect_only badge then reads "Multi-sector impact" instead of
  // "Indirect exposure", since labelling a multi-sector story as a single
  // company's indirect exposure would misstate it. null/absent = no
  // article-level descriptor available; falls back to "Indirect exposure".
  event_scope?: 'multi_sector' | null;
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
  // Strict-engine dual truth per row (spec §37/§38): the gate-validated
  // fundamental effect + tier, and the dead-zone-classified reaction.
  // Absent/null on legacy rows.
  economic_effect?: EconomicEffect | null;
  // 'secondary' is the legacy spelling of 'secondary_deep_dive' on rows
  // persisted before the executable gate; still served, never written anew.
  display_tier?: 'primary' | 'secondary_deep_dive' | 'secondary' | null;
  reaction_direction?: ReactionDirection;
  // Gated rows only (Task 16/17) -- present only when alert_is_gated, so
  // a legacy (ungated) row simply omits these keys rather than nulling
  // them (app.market.ripple_layers row dict, corrective-v4 Task 16/17).
  mechanism?: string | null;
  materiality_grade?: MaterialityGrade | null;
  confidence_band?: ConfidenceBand | null;
  impact_type?: ImpactType | null;
  expected_market_sensitivity?: MarketSensitivity | null;
  // Final-blueprint §3/§28 (Task 9), wire contract from backend Task 6 --
  // both optional, coded defensively: a legacy row (or a row served before
  // Task 6 ships) simply omits them, and the derived row-detail line
  // (directness + tier) renders nothing rather than guessing.
  causal_directness?: CausalDirectness | null;
  publication_tier?: PublicationTier | null;
  // Free-text edge description from the gate's edge ontology (§21) --
  // e.g. "input_cost", "competitor", "supply_chain". Not yet rendered by
  // any v4 surface; carried on the type so a consumer can opt in without
  // another contract change.
  edge_relation?: string | null;
  // Deterministic template (app.analysis.refinement.divergence_line):
  // non-null ONLY when economic_effect and reaction_direction point
  // opposite ways; never a prediction, only a stated fact.
  divergence?: string | null;
  // Subsystem D: empirical reaction range for this alert's news category.
  // Optional, mirroring how `fundamentals?:` above documents its
  // producers: app.market.ripple_layers rows emit it (null below sample
  // thresholds), but app.market.ripple.get_sector_peers_for_alert peer
  // rows do not set this key at all.
  volatility_range?: VolatilityRangeData | null;
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
  // Cascade derivation edges (v4 ripple network chart): who each company
  // was derived from; source null = hangs off the news event directly.
  edges?: Array<{ source: string | null; target: string; relation: string }>;
}

// GET /api/feed-v2/{id}/deep-dive (corrective-v4 Task 16, spec §52):
// gated-analysis-only surface, PRIMARY + SECONDARY_DEEP_DIVE + the
// machine-readable rejection audit trail. 404s for an ungated (legacy)
// alert -- the normal feed-v2 detail route stays the place that one is
// served from.
export interface RejectedCompany {
  ticker: string;
  rejection_reason: string | null;
  materiality_grade: string | null;
}

export interface DeepDiveResponse {
  primary: RippleLayer[];
  secondary: RippleLayer[];
  rejected_summary: RejectedCompany[];
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
  // Subsystem D: empirical reaction range for this alert's news category.
  // Sent by app.routers.stock_deep_dive -- null below sample thresholds or
  // outside alert context, never omitted from the response.
  volatility_range?: VolatilityRangeData | null;
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
  market_cap: number | null; // absolute rupees; format to crore client-side
  index_tier: string; // NIFTY50 | NIFTY100 | NIFTY500 | OTHER
  sub_sector: string | null;
  pe: number | null;
  pb: number | null;
  roe: number | null;
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

export function getAlertDeepDive(id: number, token: string | null = null): Promise<DeepDiveResponse> {
  return getJson<DeepDiveResponse>(`/api/feed-v2/${id}/deep-dive`, token);
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

export function getDirectory(token: string | null = null): Promise<DirectoryCompany[]> {
  // All filtering is client-side (directoryFilters.ts) -- one full fetch.
  return getJson<DirectoryCompany[]>('/api/feed-v2/directory', token);
}

export function getPortfolioOverlay(token: string | null): Promise<PortfolioOverlay> {
  return getJson<PortfolioOverlay>('/api/feed-v2/portfolio', token);
}

export function getCarReview(token: string | null): Promise<CarReviewRow[]> {
  return getJson<CarReviewRow[]>('/api/car-review', token);
}
