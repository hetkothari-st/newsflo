import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CompanyLogo from './CompanyLogo';

// The logo is intentionally decorative (alt="") -- the company name is
// already rendered as adjacent text in every consumer, so a screen reader
// would announce it twice with a descriptive alt. An empty-alt <img> has
// implicit role="presentation", not "img", so it must be queried by tag
// (container.querySelector) rather than screen.getByRole('img').
describe('CompanyLogo', () => {
  it('renders an img with the given logo url', () => {
    const { container } = render(<CompanyLogo logoUrl="https://cdn.brandfetch.io/ticker/AAPL?c=x" ticker="AAPL" />);
    const img = container.querySelector('img');
    expect(img).toHaveAttribute('src', 'https://cdn.brandfetch.io/ticker/AAPL?c=x');
  });

  it('shows a monogram fallback when logoUrl is null', () => {
    const { container } = render(<CompanyLogo logoUrl={null} ticker="RELIANCE.NS" />);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('RE')).toBeInTheDocument();
  });

  it('shows a monogram fallback when logoUrl is undefined', () => {
    render(<CompanyLogo logoUrl={undefined} ticker="AAPL" />);
    expect(screen.getByText('AA')).toBeInTheDocument();
  });

  it('swaps to the monogram fallback on image load error', () => {
    const { container } = render(<CompanyLogo logoUrl="https://cdn.brandfetch.io/ticker/BAD?c=x" ticker="BAD" />);
    const img = container.querySelector('img')!;
    act(() => {
      img.dispatchEvent(new Event('error'));
    });
    expect(screen.getByText('BA')).toBeInTheDocument();
  });

  it('uses the ticker prefix before any dot suffix for the monogram', () => {
    render(<CompanyLogo logoUrl={null} ticker="RELIANCE.NS" />);
    expect(screen.getByText('RE')).toBeInTheDocument();
  });
});
