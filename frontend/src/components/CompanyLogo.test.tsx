import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CompanyLogo from './CompanyLogo';
import { avatarColor, sectorColor } from '../features/visualize/colors';

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

  it('gives the monogram fallback a real, deliberate color, not a flat grey box', () => {
    render(<CompanyLogo logoUrl={null} ticker="RELIANCE.NS" />);
    const wrapper = screen.getByText('RE').parentElement;
    expect(wrapper?.style.backgroundColor).not.toBe('');
  });

  it('uses the sector color when a sector is given', () => {
    render(<CompanyLogo logoUrl={null} ticker="RELIANCE.NS" sector="oil_gas" />);
    const wrapper = screen.getByText('RE').parentElement;
    expect(wrapper?.style.backgroundColor).toBe(hexToRgb(sectorColor('oil_gas')));
  });

  it('falls back to a deterministic per-ticker color when no sector is given', () => {
    render(<CompanyLogo logoUrl={null} ticker="RELIANCE.NS" />);
    const wrapper = screen.getByText('RE').parentElement;
    expect(wrapper?.style.backgroundColor).toBe(hexToRgb(avatarColor('RELIANCE.NS')));
  });

  it('picks the same fallback color for the same ticker every render (deterministic, not random)', () => {
    const { unmount } = render(<CompanyLogo logoUrl={null} ticker="ONGC.NS" />);
    const first = screen.getByText('ON').parentElement?.style.backgroundColor;
    unmount();
    render(<CompanyLogo logoUrl={null} ticker="ONGC.NS" />);
    const second = screen.getByText('ON').parentElement?.style.backgroundColor;
    expect(first).toBe(second);
  });
});

// jsdom normalizes inline style hex colors to rgb() on read -- convert the
// expected hex the same way so these assertions compare like with like.
function hexToRgb(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgb(${r}, ${g}, ${b})`;
}
