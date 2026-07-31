// Shared deck test fixtures (Doc-1 §6): every chart must be correct with a
// sparse 3-company one-per-level alert AND a full 9-company alert.
import type { AlertArticle, AlertCompany } from '../../../lib/api';

export function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50', sector: 'banking',
    direction: 'bearish', magnitude_low: 1, magnitude_high: 2, rationale: 'rates bite here',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', confidence_score: 60,
    time_horizon: 'Short-Term', market: 'IN', in_my_holdings: false, past_mentions: [],
    impact_level: 'direct',
    ...overrides,
  };
}

export const article: AlertArticle = {
  id: 1,
  title: 'RBI raises repo rate 25 bps to 6.75%',
  url: 'https://example.com',
  image_url: null,
};

export const createdAt = '2026-07-22T10:30:00Z';

// One company per level -- the common real-world alert shape.
export const sparseCompanies: AlertCompany[] = [
  company({ company_id: 1, ticker: 'HDFCBANK', name: 'HDFC Bank', impact_level: 'direct', excess_move_pct: -1.4, confidence_score: 88, time_horizon: 'Immediate' }),
  company({ company_id: 2, ticker: 'BAJFINANCE', name: 'Bajaj Finance', impact_level: 'indirect_l1', parent_company_id: 1, confidence_score: 64, sector: 'banking', sub_sector: 'nbfc', time_horizon: 'Short-Term' }),
  company({ company_id: 3, ticker: 'DLF', name: 'DLF', impact_level: 'indirect_l2', parent_company_id: 2, confidence_score: 42, sector: 'infra', direction: 'bearish', time_horizon: 'Medium-Term' }),
];

export const fullCompanies: AlertCompany[] = [
  company({ company_id: 1, ticker: 'HDFCBANK', name: 'HDFC Bank', impact_level: 'direct', excess_move_pct: -1.4, confidence_score: 88, time_horizon: 'Immediate' }),
  company({ company_id: 2, ticker: 'ICICIBANK', name: 'ICICI Bank', impact_level: 'direct', excess_move_pct: -1.2, confidence_score: 84, time_horizon: 'Immediate' }),
  company({ company_id: 3, ticker: 'SBIN', name: 'State Bank', impact_level: 'direct', excess_move_pct: -1.0, confidence_score: 78, time_horizon: 'Short-Term' }),
  company({ company_id: 4, ticker: 'BAJFINANCE', name: 'Bajaj Finance', impact_level: 'indirect_l1', parent_company_id: 1, excess_move_pct: -2.1, confidence_score: 66, sub_sector: 'nbfc', time_horizon: 'Short-Term' }),
  company({ company_id: 5, ticker: 'DLF', name: 'DLF', impact_level: 'indirect_l1', parent_company_id: 2, excess_move_pct: -1.9, confidence_score: 61, sector: 'infra', time_horizon: 'Medium-Term' }),
  company({ company_id: 6, ticker: 'MARUTI', name: 'Maruti Suzuki', impact_level: 'indirect_l1', parent_company_id: 1, excess_move_pct: -0.8, confidence_score: 55, sector: 'auto', time_horizon: 'Medium-Term' }),
  company({ company_id: 7, ticker: 'ULTRACEMCO', name: 'UltraTech', impact_level: 'indirect_l2', parent_company_id: 5, excess_move_pct: -0.6, confidence_score: 48, sector: 'infra', time_horizon: 'Long-Term' }),
  company({ company_id: 8, ticker: 'HINDUNILVR', name: 'Hind. Unilever', impact_level: 'indirect_l2', parent_company_id: 4, excess_move_pct: 0.7, confidence_score: 44, sector: 'fmcg', direction: 'bullish', time_horizon: 'Long-Term' }),
  company({ company_id: 9, ticker: 'NESTLEIND', name: 'Nestle India', impact_level: 'indirect_l2', parent_company_id: 4, excess_move_pct: 0.5, confidence_score: 38, sector: 'fmcg', direction: 'bullish', time_horizon: 'Long-Term' }),
];
