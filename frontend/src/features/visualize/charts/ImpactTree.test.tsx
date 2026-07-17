import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ImpactTree from './ImpactTree';
import type { AlertArticle, AlertCompany } from '../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50', sector: 'oil_gas',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', confidence_score: 50,
    time_horizon: 'Short-Term', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

const article: AlertArticle = { id: 1, title: 'RBI increases repo rate by 25 bps', url: 'https://example.com', image_url: null };

describe('ImpactTree', () => {
  it('renders wrapped in ChartCardShell with number 1 and title Multi-Level Impact Tree', () => {
    render(<ImpactTree companies={[]} article={article} alertCreatedAt="2026-07-17T10:30:00Z" />);
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('Multi-Level Impact Tree')).toBeInTheDocument();
  });

  it('renders the news article title', () => {
    render(<ImpactTree companies={[]} article={article} alertCreatedAt="2026-07-17T10:30:00Z" />);
    expect(screen.getByText('RBI increases repo rate by 25 bps')).toBeInTheDocument();
  });

  it('renders a direct-impact sector and its company as Level 1/2', () => {
    render(
      <ImpactTree
        companies={[company({ company_id: 1, impact_level: 'direct', sector: 'banking', ticker: 'HDFCBANK' })]}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('Banking')).toBeInTheDocument();
    expect(screen.getByText('HDFCBANK')).toBeInTheDocument();
  });

  it('renders an indirect company\'s sub-sector and ticker as Level 3/4', () => {
    render(
      <ImpactTree
        companies={[
          company({ company_id: 1, impact_level: 'indirect_l1', sector: 'banking', sub_sector: 'nbfc', ticker: 'BAJFINANCE' }),
        ]}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('NBFC')).toBeInTheDocument();
    expect(screen.getByText('BAJFINANCE')).toBeInTheDocument();
  });

  it('shows an empty note instead of Level 3/4 when there are no indirect companies', () => {
    render(
      <ImpactTree
        companies={[company({ company_id: 1, impact_level: 'direct' })]}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('No indirect ripple effects identified.')).toBeInTheDocument();
  });

  it('shows an empty note instead of Level 1/2 when there are no direct companies', () => {
    render(
      <ImpactTree
        companies={[company({ company_id: 1, impact_level: 'indirect_l1', sub_sector: 'nbfc' })]}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('No direct impact identified.')).toBeInTheDocument();
  });
});
