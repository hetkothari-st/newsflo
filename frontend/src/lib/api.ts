// Response shapes copied verbatim from the backend routers. These interfaces
// are the single source of truth for every component in the app.

export interface AlertArticle {
  id: number;
  title: string;
  url: string;
  image_url: string | null;
}

export interface AlertCompany {
  company_id: number;
  ticker: string;
  name: string;
  index_tier: string; // NIFTY50 | NIFTY100 | NIFTY500 | GLOBAL_LARGE_CAP | OTHER
  direction: string; // bullish | bearish
  magnitude_low: number;
  magnitude_high: number;
  rationale: string;
  key_points: string[]; // short, scannable version of `rationale` -- empty for legacy alerts
  basis: string; // direct_mention | sector_inference
  confidence: string; // llm_estimate | calibrated
  market: 'IN' | 'GLOBAL';
  in_my_holdings: boolean;
}

export interface Alert {
  id: number;
  category: string;
  created_at: string;
  article: AlertArticle;
  companies: AlertCompany[];
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
  image_url: string | null;
  fetched_at: string | null;
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
  index_tier: string;
  market: 'IN' | 'GLOBAL';
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

export async function getAlerts(token: string | null = null): Promise<Alert[]> {
  const res = await fetch('/api/alerts', { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Alert[];
}

export async function getArticles(): Promise<Article[]> {
  const res = await fetch('/api/articles');
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Article[];
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

export async function getCategories(): Promise<string[]> {
  const res = await fetch('/api/categories');
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as string[];
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
