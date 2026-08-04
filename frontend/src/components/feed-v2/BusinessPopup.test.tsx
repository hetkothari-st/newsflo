import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import BusinessPopup from './BusinessPopup';

describe('BusinessPopup', () => {
  it('renders ticker, sector, and cap tier', () => {
    render(<BusinessPopup ticker="RELIANCE.NS" sector="oil_gas" capTier="LARGE" fundamentals={null} />);
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
    expect(screen.getByText('oil_gas')).toBeInTheDocument();
    expect(screen.getByText('LARGE')).toBeInTheDocument();
  });

  it('renders the sourced classification, ratios, and as-of date when fundamentals is present', () => {
    render(
      <BusinessPopup
        ticker="RELIANCE.NS"
        sector="oil_gas"
        capTier="LARGE"
        fundamentals={{
          classification: {
            sector: 'Energy',
            industry: 'Oil, Gas & Consumable Fuels',
            group: 'Petroleum Products',
            sub_group: 'Refineries & Marketing',
          },
          ratios: { pe: 44.95 },
          source: 'BSE',
          as_of: '2026-08-04',
        }}
      />,
    );
    expect(screen.getByText(/Refineries & Marketing/)).toBeInTheDocument();
    expect(screen.getByText('44.95')).toBeInTheDocument();
    // The date is load-bearing, not decoration: PE is price-derived and this
    // data refreshes monthly (spec 5.1).
    expect(screen.getByText(/2026-08-04/)).toBeInTheDocument();
  });

  it('renders no placeholder text and no second panel when fundamentals is null', () => {
    render(<BusinessPopup ticker="RELIANCE.NS" sector="oil_gas" capTier="LARGE" fundamentals={null} />);
    expect(screen.queryByText(/not available/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId('fundamentals')).not.toBeInTheDocument();
  });

  it('renders no placeholder text and no second panel when fundamentals is undefined', () => {
    render(<BusinessPopup ticker="RELIANCE.NS" sector="oil_gas" capTier="LARGE" />);
    expect(screen.queryByText(/not available/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId('fundamentals')).not.toBeInTheDocument();
  });

  it('omits the cap tier tag when it is null', () => {
    render(<BusinessPopup ticker="RELIANCE.NS" sector="oil_gas" capTier={null} fundamentals={null} />);
    expect(screen.queryByText('LARGE')).not.toBeInTheDocument();
    expect(screen.queryByText('MID')).not.toBeInTheDocument();
    expect(screen.queryByText('SMALL')).not.toBeInTheDocument();
  });
});
