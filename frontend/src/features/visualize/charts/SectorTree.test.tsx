import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import SectorTree from './SectorTree';
import type { AlertCompany } from '../../../lib/api';
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

describe('SectorTree', () => {
  it('renders one branch per sector present, labeled with the human-readable name', () => {
    render(
      <SectorTree
        companies={[
          company({ company_id: 1, sector: 'oil_gas', ticker: 'RIL' }),
          company({ company_id: 2, sector: 'banking', ticker: 'HDFCBANK', direction: 'bearish' }),
        ]}
      />,
    );
    expect(screen.getByText('Oil & Gas')).toBeInTheDocument();
    expect(screen.getByText('Banking')).toBeInTheDocument();
    expect(screen.getByText('RIL')).toBeInTheDocument();
    expect(screen.getByText('HDFCBANK')).toBeInTheDocument();
  });

  it('collapses a sector branch on tap, hiding its companies', async () => {
    render(<SectorTree companies={[company({ company_id: 1, sector: 'oil_gas', ticker: 'RIL' })]} />);
    expect(screen.getByText('RIL')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Oil & Gas'));
    expect(screen.queryByText('RIL')).not.toBeInTheDocument();
  });

  it('expands a ReasoningPanel when a company is tapped', async () => {
    render(<SectorTree companies={[company({ company_id: 1, rationale: 'Refiner margins widen on lower crude.' })]} />);
    await userEvent.click(screen.getByText('AAA'));
    expect(screen.getByText(/Refiner margins widen/)).toBeInTheDocument();
  });

  it('renders nothing for an empty company list', () => {
    const { container } = render(<SectorTree companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders sub-sector branches when a sector has more than one distinct sub_sector', () => {
    render(
      <SectorTree
        companies={[
          company({ company_id: 1, sector: 'banking', sub_sector: 'private_bank', ticker: 'HDFCBANK' }),
          company({ company_id: 2, sector: 'banking', sub_sector: 'psu_bank', ticker: 'SBIN' }),
        ]}
      />,
    );
    expect(screen.getByText('Private Bank')).toBeInTheDocument();
    expect(screen.getByText('PSU Bank')).toBeInTheDocument();
  });

  it('collapses to a flat sector -> company view when only one sub_sector bucket is present', () => {
    render(
      <SectorTree
        companies={[
          company({ company_id: 1, sector: 'banking', sub_sector: null, ticker: 'HDFCBANK' }),
          company({ company_id: 2, sector: 'banking', sub_sector: null, ticker: 'SBIN' }),
        ]}
      />,
    );
    expect(screen.queryByText('Unclassified')).not.toBeInTheDocument();
    expect(screen.getByText('HDFCBANK')).toBeInTheDocument();
    expect(screen.getByText('SBIN')).toBeInTheDocument();
  });

  it('buckets legacy companies with no sub_sector as Unclassified alongside a classified sibling', () => {
    render(
      <SectorTree
        companies={[
          company({ company_id: 1, sector: 'banking', sub_sector: 'private_bank', ticker: 'HDFCBANK' }),
          company({ company_id: 2, sector: 'banking', sub_sector: null, ticker: 'SBIN' }),
        ]}
      />,
    );
    expect(screen.getByText('Private Bank')).toBeInTheDocument();
    expect(screen.getByText('Unclassified')).toBeInTheDocument();
  });
});
