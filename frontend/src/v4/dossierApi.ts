/* Company dossier API client -- its own module (not v3/api.ts) so the
   dossier feature stays isolated and merge-friendly. */
import type { Fundamentals } from '../lib/api';

export interface DossierListing {
  exchange: 'NSE' | 'BSE';
  symbol: string;
  scrip_code: string | null;
  series: string | null;
  group_code: string | null;
  status: string;
  face_value: number | null;
  listed_on: string | null;
}

export interface DossierNewsItem {
  alert_id: number;
  title: string;
  url: string;
  created_at: string;
  category: string;
  direction: 'bullish' | 'bearish';
  excess_move_pct: number | null;
}

export interface CompanyDossier {
  id: number;
  ticker: string;
  name: string;
  sector: string;
  sub_sector: string | null;
  isin: string | null;
  logo_url: string | null;
  cap_tier: string | null;
  listings: DossierListing[];
  indices: string[];
  fundamentals: Fundamentals | null;
  business_desc: string | null;
  business_desc_source_url: string | null;
  market_cap: number | null;
  market_cap_source: 'live' | 'stored' | null;
  news: DossierNewsItem[];
  track_record: Record<string, { win_rate: number; sample_size: number }> | null;
  history_text: string | null;
  history_source_url: string | null;
  developments_text: string | null;
  developments_source_url: string | null;
}

export interface PricePoint {
  date: string;
  close: number;
}

export interface LivePrice {
  ltp: number | null;
  change_pct: number | null;
  as_of: string | null;
  available: boolean;
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return (await res.json()) as T;
}

export function getCompanyDossier(ticker: string): Promise<CompanyDossier> {
  return getJson<CompanyDossier>(`/api/companies/by-ticker/${encodeURIComponent(ticker)}/dossier`);
}

export function getPriceSeries(companyId: number, period: string): Promise<{ points: PricePoint[]; available: boolean }> {
  return getJson(`/api/companies/${companyId}/prices?period=${period}`);
}

export function getLivePrice(companyId: number): Promise<LivePrice> {
  return getJson<LivePrice>(`/api/companies/${companyId}/live-price`);
}

/* Human labels for NSE index codes -- display only, raw code when unmapped. */
const INDEX_LABELS: Record<string, string> = {
  NIFTY50: 'NIFTY 50',
  NIFTYNEXT50: 'NIFTY NEXT 50',
  NIFTY100: 'NIFTY 100',
  NIFTY500: 'NIFTY 500',
  NIFTYBANK: 'NIFTY BANK',
  NIFTYIT: 'NIFTY IT',
  NIFTYPHARMA: 'NIFTY PHARMA',
  NIFTYAUTO: 'NIFTY AUTO',
  NIFTYFMCG: 'NIFTY FMCG',
  NIFTYREALTY: 'NIFTY REALTY',
  NIFTYMIDCAP150: 'NIFTY MIDCAP 150',
  NIFTYSMALLCAP250: 'NIFTY SMALLCAP 250',
  NIFTYPVTBANK: 'NIFTY PVT BANK',
  NIFTYPSUBANK: 'NIFTY PSU BANK',
  NIFTYPSE: 'NIFTY PSE',
  NIFTYCPSE: 'NIFTY CPSE',
};

export function indexLabel(code: string): string {
  return INDEX_LABELS[code] ?? code.replace(/^NIFTY/, 'NIFTY ');
}
