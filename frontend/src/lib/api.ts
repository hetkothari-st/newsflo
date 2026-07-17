// Response shapes copied verbatim from the backend routers. These interfaces
// are the single source of truth for every component in the app.

import type { Language } from './i18n';

export interface AlertArticle {
  id: number;
  title: string;
  url: string;
  image_url: string | null;
}

export interface PastMention {
  alert_id: number;
  article_title: string;
  article_url: string;
  created_at: string;
  direction: string; // bullish | bearish
  category: string;
}

export interface AlertCompany {
  company_id: number;
  ticker: string;
  name: string;
  index_tier: string; // NIFTY50 | NIFTY100 | NIFTY500 | GLOBAL_LARGE_CAP | OTHER
  sector?: string;
  // One of backend app.companies.sub_sectors.SUB_SECTOR_TAXONOMY[sector], or
  // null until the one-time enrichment backfill classifies it (or forever,
  // for sector === 'other'). Render null as an "Unclassified" bucket, never
  // filter it out silently.
  sub_sector?: string | null;
  // Real company logo from Brandfetch (see backend app.companies.branding),
  // null when no BRANDFETCH_CLIENT_ID is configured or Brandfetch has no
  // match for this company -- CompanyLogo degrades to a monogram either way.
  logo_url?: string | null;
  direction: string; // bullish | bearish
  magnitude_low: number;
  magnitude_high: number;
  rationale: string;
  key_points: string[]; // short, scannable version of `rationale` -- empty for legacy alerts
  confidence_score: number; // 0-100, how directly evidenced this company's call is
  time_horizon: string; // Immediate | Short-Term | Medium-Term | Long-Term
  basis: string; // direct_mention | sector_inference
  confidence: string; // llm_estimate | calibrated
  market: 'IN' | 'GLOBAL';
  in_my_holdings: boolean;
  past_mentions: PastMention[]; // this company's prior alerts, most recent first
  // Reasoning-engine fields (see docs/superpowers/specs/2026-07-15-
  // reasoning-engine-upgrade-design.md). Optional because ~27 existing test
  // fixtures construct AlertCompany literals without them -- a legacy alert
  // (persisted before this feature shipped) also genuinely has none of
  // these, degrading to undefined/null exactly like a pre-feature alert.
  confidence_band?: string | null; // LOW | MODERATE | HIGH | VERY_HIGH | null
  reasons?: string[];
  evidence_refs?: string[];
  risks?: string[];
  assumptions?: string[];
  unknowns?: string[];
  alternative_hypothesis?: string | null;
  confidence_contributors?: string[];
  confidence_penalties?: string[];
  // Financial grounding + contradiction detection (see docs/superpowers/
  // specs/2026-07-16-financial-grounding-contradiction-detection-design.md).
  // Optional/nullable for the same reason as the reasoning-engine fields
  // above: legacy alerts and existing test fixtures don't have these.
  price_at_analysis?: number | null;
  return_1m?: number | null;
  return_3m?: number | null;
  contradiction_note?: string | null;
  // How far removed this company's impact is from the article's direct
  // subject: 'direct' | 'indirect_l1' | 'indirect_l2'. Defaults to 'direct'
  // for legacy alerts predating this field. See parent_company_id for the
  // company an indirect entry is economically linked through.
  impact_level?: string;
  parent_company_id?: number | null;
}

export interface Alert {
  id: number;
  // Raw, canonical, untranslated category slug -- used for watchlist
  // matching and swatch-color lookup. Never render this directly in a
  // non-English UI; use `category_label` for display.
  category: string;
  category_label: string;
  created_at: string;
  article: AlertArticle;
  companies: AlertCompany[];
  // Optional: legacy alerts (persisted before this feature shipped) have
  // no event_type.
  event_type?: string | null;
}

// The WebSocket live-push payload is one alert entry MINUS the per-viewer
// in_my_holdings flag (see Part A). useAlertsSocket normalizes it back to Alert
// by defaulting in_my_holdings to false.
export type WsAlertCompany = Omit<AlertCompany, 'in_my_holdings'>;
export type WsAlert = Omit<Alert, 'companies'> & { companies: WsAlertCompany[] };

export interface Article {
  id: number;
  source: string;
  title: string;
  url: string;
  status: string;
  category: string | null;
  category_label: string | null;
  image_url: string | null;
  fetched_at: string | null;
}

export interface CategoryOption {
  category: string;
  label: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface Holding {
  company_id: number;
  ticker: string;
  name: string;
  quantity: number;
}

export interface CsvUploadResponse {
  loaded: number;
}

export interface Company {
  id: number;
  ticker: string;
  name: string;
  sector: string;
  sub_sector?: string | null;
  index_tier: string;
  market: 'IN' | 'GLOBAL';
  isin: string | null;
  logo_url: string | null;
}

export interface WatchlistCompany {
  company_id: number;
  ticker: string;
  name: string;
}

export interface Watchlist {
  categories: string[];
  companies: WatchlistCompany[];
}

export interface Profile {
  id: number;
  email: string;
  created_at: string;
  email_alerts_enabled: boolean;
}

export interface LatestAlertSignal {
  alert_id: number;
  created_at: string;
  direction: string; // bullish | bearish
  rationale: string;
  key_points: string[];
  confidence: string; // llm_estimate | calibrated
  category: string;
  category_label: string;
  article: AlertArticle;
}

export interface HorizonStats {
  win_rate: number;
  sample_size: number;
}

// Keyed by horizon_days as a string ("1" | "3" | "7"); a horizon is present
// only once it has enough calibration samples (see backend WIN_RATE_SAMPLE_THRESHOLD).
export type TrackRecord = Record<string, HorizonStats>;

export interface CompanyProfile extends Company {
  latest_alert: LatestAlertSignal | null;
  track_record: TrackRecord | null;
}

export interface CompanyHistoryPage {
  mentions: PastMention[];
  has_more: boolean;
}

export interface PricePoint {
  date: string;
  close: number;
}

export type PricePeriod = '1mo' | '3mo' | '6mo' | '1y';

export interface PriceSeries {
  period: string;
  points: PricePoint[];
  available: boolean;
}

export interface LivePrice {
  ltp: number | null;
  change_pct: number | null;
  as_of: string | null;
  available: boolean;
}

interface ApiError {
  detail: string;
}

function authHeaders(token: string | null): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
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

export async function getAlerts(token: string | null = null, lang: Language = 'en'): Promise<Alert[]> {
  const res = await fetch(`/api/alerts?lang=${lang}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Alert[];
}

export async function getAlert(id: number, token: string | null = null, lang: Language = 'en'): Promise<Alert> {
  const res = await fetch(`/api/alerts/${id}?lang=${lang}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Alert;
}

export async function getArticles(lang: Language = 'en'): Promise<Article[]> {
  const res = await fetch(`/api/articles?lang=${lang}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Article[];
}

// Keyed by ISO date ("YYYY-MM-DD", IST calendar day) -> alert count that day.
// Zero-count days are simply absent from the map.
export type CalendarCounts = Record<string, number>;

export async function getCalendarCounts(year: number, month: number): Promise<CalendarCounts> {
  const res = await fetch(`/api/calendar/counts?year=${year}&month=${month}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as CalendarCounts;
}

export async function getCalendarDay(date: string, lang: Language = 'en'): Promise<Alert[]> {
  const res = await fetch(`/api/calendar/day?date=${date}&lang=${lang}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Alert[];
}

export async function getCompanyProfile(id: number, lang: Language = 'en'): Promise<CompanyProfile | null> {
  const res = await fetch(`/api/companies/${id}/profile?lang=${lang}`);
  // 404 (unknown id, or a non-Indian company this page doesn't support yet)
  // is an expected "not found" UI state here, not a thrown error.
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as CompanyProfile;
}

export async function getCompanyHistory(id: number, before?: string, limit = 20): Promise<CompanyHistoryPage> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (before) params.set('before', before);
  const res = await fetch(`/api/companies/${id}/history?${params}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as CompanyHistoryPage;
}

export async function getCompanyPrices(id: number, period: PricePeriod = '6mo'): Promise<PriceSeries> {
  const res = await fetch(`/api/companies/${id}/prices?period=${period}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as PriceSeries;
}

export async function getCompanyLivePrice(id: number): Promise<LivePrice> {
  // no-store: this is polled every few seconds -- without it the browser's
  // HTTP cache can silently serve a stale response to a repeat fetch() call
  // against the same URL, freezing the displayed price until a hard reload.
  const res = await fetch(`/api/companies/${id}/live-price`, { cache: 'no-store' });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as LivePrice;
}

export async function register(email: string, password: string): Promise<TokenResponse> {
  const res = await fetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as TokenResponse;
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as TokenResponse;
}

export async function getHoldings(token: string): Promise<Holding[]> {
  const res = await fetch('/api/holdings', { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Holding[];
}

export async function addHolding(token: string, ticker: string, quantity: number): Promise<Holding> {
  const res = await fetch('/api/holdings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ ticker, quantity }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Holding;
}

export async function uploadHoldingsCsv(token: string, file: File): Promise<CsvUploadResponse> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch('/api/holdings/csv', {
    method: 'POST',
    headers: authHeaders(token),
    body: form,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as CsvUploadResponse;
}

export async function getCompanies(market?: 'IN' | 'GLOBAL'): Promise<Company[]> {
  const query = market ? `?market=${market}` : '';
  const res = await fetch(`/api/companies${query}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Company[];
}

export async function getCategories(lang: Language = 'en'): Promise<CategoryOption[]> {
  const res = await fetch(`/api/categories?lang=${lang}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as CategoryOption[];
}

export async function getWatchlist(token: string): Promise<Watchlist> {
  const res = await fetch('/api/watchlist', { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Watchlist;
}

export async function putWatchlist(
  token: string,
  categories: string[],
  companyIds: number[],
): Promise<Watchlist> {
  const res = await fetch('/api/watchlist', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ categories, company_ids: companyIds }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Watchlist;
}

export interface TranslationStatus {
  total: number;
  translated: number;
  running: boolean;
}

// Kicks off an on-demand backend translation drain for `lang` (bounded to
// the most recent alerts -- see backend/app/routers/translation.py). A
// no-op for English. Fire-and-forget: progress is observed via
// getTranslationStatus, not this response.
export async function triggerTranslation(lang: Language): Promise<{ started: boolean }> {
  const res = await fetch(`/api/translation/run?lang=${lang}`, { method: 'POST' });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as { started: boolean };
}

export async function getTranslationStatus(lang: Language): Promise<TranslationStatus> {
  const res = await fetch(`/api/translation/status?lang=${lang}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as TranslationStatus;
}

export async function getMe(token: string): Promise<Profile> {
  const res = await fetch('/api/auth/me', { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Profile;
}

export async function updatePreferences(token: string, emailAlertsEnabled: boolean): Promise<Profile> {
  const res = await fetch('/api/auth/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ email_alerts_enabled: emailAlertsEnabled }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Profile;
}

export async function changePassword(
  token: string,
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const res = await fetch('/api/auth/me/password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (!res.ok) throw new Error(await parseError(res));
}

export async function deleteAccount(token: string, password: string): Promise<void> {
  const res = await fetch('/api/auth/me', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
}
