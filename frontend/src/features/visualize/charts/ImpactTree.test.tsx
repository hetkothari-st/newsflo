import { render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import ImpactTree from './ImpactTree';
import type { AlertArticle, AlertCompany } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

function render(ui: ReactElement) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>{ui}</LanguageProvider>
    </MemoryRouter>,
  );
}

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

  it('shows the highest-confidence company\'s rationale as the sector\'s explanation', () => {
    render(
      <ImpactTree
        companies={[
          company({ company_id: 1, impact_level: 'direct', sector: 'banking', confidence_score: 40, rationale: 'Lower rationale.' }),
          company({ company_id: 2, impact_level: 'direct', sector: 'banking', confidence_score: 90, rationale: 'Rate cut directly compresses net interest margins.' }),
        ]}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('Rate cut directly compresses net interest margins.')).toBeInTheDocument();
    expect(screen.queryByText('Lower rationale.')).not.toBeInTheDocument();
  });

  it('shows the highest-confidence company\'s rationale as the sub-sector\'s explanation', () => {
    render(
      <ImpactTree
        companies={[
          company({
            company_id: 1,
            impact_level: 'indirect_l1',
            sub_sector: 'nbfc',
            confidence_score: 70,
            rationale: 'NBFCs face higher funding costs as rates rise.',
          }),
        ]}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    expect(screen.getByText('NBFCs face higher funding costs as rates rise.')).toBeInTheDocument();
  });

  it('expands a ReasoningPanel when a direct company is tapped', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    render(
      <ImpactTree
        companies={[company({ company_id: 1, ticker: 'HDFCBANK', sector: 'banking', impact_level: 'direct', rationale: 'Lower rates lift loan demand.' })]}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    // The sole company's rationale is already shown once, unconditionally, by
    // the sector's WhyExplanation summary -- so a plain getByText match would
    // pass even without any click wiring. Assert on the second occurrence
    // that only the expanded ReasoningPanel adds.
    await userEvent.click(screen.getByText('HDFCBANK'));
    expect(screen.getAllByText(/Lower rates lift loan demand/)).toHaveLength(2);
  });

  it('expands a ReasoningPanel when an indirect (sub-sector) company is tapped', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    render(
      <ImpactTree
        companies={[company({
          company_id: 1, ticker: 'ULTRACEMCO', sector: 'infra', impact_level: 'indirect_l1',
          parent_company_id: 99, rationale: 'Cement demand rises with construction activity.',
        })]}
        article={article}
        alertCreatedAt="2026-07-17T10:30:00Z"
      />,
    );
    // Same reasoning as the direct-company case above: the sub-sector's
    // WhyExplanation already shows this sole company's rationale unconditionally.
    await userEvent.click(screen.getByText('ULTRACEMCO'));
    expect(screen.getAllByText(/Cement demand rises/)).toHaveLength(2);
  });
});
