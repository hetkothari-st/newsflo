import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import BusinessPopup from './BusinessPopup';

describe('BusinessPopup', () => {
  it('renders ticker, sector, and cap tier', () => {
    render(
      <BusinessPopup
        ticker="RELIANCE.NS"
        sector="oil_gas"
        capTier="LARGE"
        businessDesc="Refines crude oil and runs retail fuel outlets."
      />,
    );
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
    expect(screen.getByText('oil_gas')).toBeInTheDocument();
    expect(screen.getByText('LARGE')).toBeInTheDocument();
  });

  it('renders the business description when present', () => {
    render(
      <BusinessPopup
        ticker="RELIANCE.NS"
        sector="oil_gas"
        capTier="LARGE"
        businessDesc="Refines crude oil and runs retail fuel outlets."
      />,
    );
    expect(screen.getByText('Refines crude oil and runs retail fuel outlets.')).toBeInTheDocument();
  });

  it('renders a fallback message when business description is unavailable', () => {
    render(<BusinessPopup ticker="RELIANCE.NS" sector="oil_gas" capTier="LARGE" businessDesc={null} />);
    expect(screen.getByText(/not available/i)).toBeInTheDocument();
  });

  it('omits the cap tier tag when it is null', () => {
    render(<BusinessPopup ticker="RELIANCE.NS" sector="oil_gas" capTier={null} businessDesc="d" />);
    expect(screen.queryByText('LARGE')).not.toBeInTheDocument();
    expect(screen.queryByText('MID')).not.toBeInTheDocument();
    expect(screen.queryByText('SMALL')).not.toBeInTheDocument();
  });
});
