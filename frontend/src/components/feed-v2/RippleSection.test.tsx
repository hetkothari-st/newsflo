import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import RippleSection from './RippleSection';
import type { RippleCompany } from '../../lib/feedV2Api';

function makeCompany(overrides: Partial<RippleCompany> = {}): RippleCompany {
  return {
    ticker: 'BPCL.NS',
    name: 'Bharat Petroleum',
    relationship: 'BENEFICIARY',
    direction: 'bullish',
    excess_move_pct: 3.0,
    intensity: { score: 70, band: 'Moderate', components: [] },
    is_exposure_only: false,
    in_my_holdings: false,
    ...overrides,
  };
}

describe('RippleSection', () => {
  it('renders nothing when there are no companies', () => {
    const { container } = render(<RippleSection companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('groups companies by relationship with a count label', () => {
    render(
      <RippleSection
        companies={[
          makeCompany({ ticker: 'A.NS', relationship: 'BENEFICIARY' }),
          makeCompany({ ticker: 'B.NS', relationship: 'BENEFICIARY' }),
          makeCompany({ ticker: 'C.NS', relationship: 'COMPETITOR' }),
        ]}
      />,
    );
    expect(screen.getByText('Beneficiary (2)')).toBeInTheDocument();
    expect(screen.getByText('Competitor (1)')).toBeInTheDocument();
  });

  it('renders ticker, excess, and intensity bar for a measured company', () => {
    render(<RippleSection companies={[makeCompany({ ticker: 'BPCL.NS', excess_move_pct: 3.0 })]} />);
    expect(screen.getByText('BPCL.NS')).toBeInTheDocument();
    expect(screen.getByText(/3\.0%/)).toBeInTheDocument();
  });

  it('renders an Exposure label with no number for an exposure-only company', () => {
    render(
      <RippleSection
        companies={[
          makeCompany({
            ticker: 'GAIL.NS', is_exposure_only: true, excess_move_pct: null, intensity: null,
          }),
        ]}
      />,
    );
    expect(screen.getByText('GAIL.NS')).toBeInTheDocument();
    expect(screen.getByText('Exposure')).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('renders an owned dot only when in_my_holdings is true', () => {
    const { rerender, container } = render(
      <RippleSection companies={[makeCompany({ in_my_holdings: false })]} />,
    );
    expect(container.querySelector('[data-testid="ripple-owned-dot"]')).not.toBeInTheDocument();

    rerender(<RippleSection companies={[makeCompany({ in_my_holdings: true })]} />);
    expect(container.querySelector('[data-testid="ripple-owned-dot"]')).toBeInTheDocument();
  });

  it('omits a relationship group entirely when it has no companies', () => {
    render(<RippleSection companies={[makeCompany({ relationship: 'BENEFICIARY' })]} />);
    expect(screen.queryByText(/Substitute/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Sector wide/)).not.toBeInTheDocument();
  });
});
