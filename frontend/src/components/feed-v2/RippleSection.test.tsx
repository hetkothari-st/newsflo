import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import RippleSection from './RippleSection';
import type { RippleCompany } from '../../lib/feedV2Api';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

function makeCompany(overrides: Partial<RippleCompany> = {}): RippleCompany {
  return {
    ticker: 'BPCL.NS',
    name: 'Bharat Petroleum',
    sector: 'oil_gas',
    cap_tier: 'LARGE',
    business_desc: 'Refines and markets petroleum products.',
    relationship: 'BENEFICIARY',
    direction: 'bullish',
    excess_move_pct: 3.0,
    intensity: { score: 70, band: 'Moderate', components: [] },
    is_exposure_only: false,
    in_my_holdings: false,
    ...overrides,
  };
}

function renderSection(companies: RippleCompany[], alertId = 42) {
  render(
    <MemoryRouter>
      <RippleSection companies={companies} alertId={alertId} />
    </MemoryRouter>,
  );
}

describe('RippleSection', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  it('renders nothing when there are no companies', () => {
    const { container } = render(
      <MemoryRouter>
        <RippleSection companies={[]} alertId={42} />
      </MemoryRouter>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('groups companies by relationship with a count label', () => {
    renderSection([
      makeCompany({ ticker: 'A.NS', relationship: 'BENEFICIARY' }),
      makeCompany({ ticker: 'B.NS', relationship: 'BENEFICIARY' }),
      makeCompany({ ticker: 'C.NS', relationship: 'COMPETITOR' }),
    ]);
    expect(screen.getByText('Beneficiary (2)')).toBeInTheDocument();
    expect(screen.getByText('Competitor (1)')).toBeInTheDocument();
  });

  it('renders ticker, cap tag, excess, and intensity score for a measured company', () => {
    renderSection([makeCompany({ ticker: 'BPCL.NS', cap_tier: 'LARGE', excess_move_pct: 3.0 })]);
    expect(screen.getByText('BPCL.NS')).toBeInTheDocument();
    expect(screen.getByText('LARGE')).toBeInTheDocument();
    expect(screen.getByText(/3\.0%/)).toBeInTheDocument();
  });

  it('renders an Exposure label with no number for an exposure-only company', () => {
    renderSection([
      makeCompany({
        ticker: 'GAIL.NS', is_exposure_only: true, excess_move_pct: null, intensity: null,
      }),
    ]);
    expect(screen.getByText('GAIL.NS')).toBeInTheDocument();
    expect(screen.getByText('Exposure')).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('renders an owned dot only when in_my_holdings is true', () => {
    const { rerender, container } = render(
      <MemoryRouter>
        <RippleSection companies={[makeCompany({ in_my_holdings: false })]} alertId={42} />
      </MemoryRouter>,
    );
    expect(container.querySelector('[data-testid="peer-row-owned-dot"]')).not.toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <RippleSection companies={[makeCompany({ in_my_holdings: true })]} alertId={42} />
      </MemoryRouter>,
    );
    expect(container.querySelector('[data-testid="peer-row-owned-dot"]')).toBeInTheDocument();
  });

  it('omits a relationship group entirely when it has no companies', () => {
    renderSection([makeCompany({ relationship: 'BENEFICIARY' })]);
    expect(screen.queryByText(/Substitute/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Sector wide/)).not.toBeInTheDocument();
  });

  it('navigates to the deep-dive with alertId when a row is tapped', () => {
    renderSection([makeCompany({ ticker: 'BPCL.NS' })], 42);
    fireEvent.click(screen.getByRole('button', { name: /BPCL\.NS/ }));
    expect(mockNavigate).toHaveBeenCalledWith('/feed-v2/stock/BPCL.NS?alertId=42');
  });

  it('opens the business popup and does not navigate when (i) is tapped', () => {
    renderSection([makeCompany({ ticker: 'BPCL.NS' })], 42);
    fireEvent.click(screen.getByLabelText('View business details'));
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(screen.getByText('Refines and markets petroleum products.')).toBeInTheDocument();
  });
});
