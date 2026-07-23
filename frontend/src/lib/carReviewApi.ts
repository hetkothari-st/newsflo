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
  outcome_label: CarOutcomeLabel;
}

export interface CarReviewCategorySummary {
  category: string;
  sample_count: number;
  hold_rate: number | null;
  mean_car_pct: number | null;
}

export interface CarReviewSummary {
  sample_count: number;
  hold_rate: number | null;
  mean_car_pct: number | null;
  by_category: CarReviewCategorySummary[];
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

export async function getCarReview(token: string | null): Promise<CarReviewRow[]> {
  const res = await fetch('/api/car-review', { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as CarReviewRow[];
}

export async function getCarReviewSummary(token: string | null): Promise<CarReviewSummary> {
  const res = await fetch('/api/car-review/summary', { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as CarReviewSummary;
}
