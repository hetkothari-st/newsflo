import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import LivePriceReadout from './LivePriceReadout';
import { LanguageProvider } from '../lib/language';
import type { LivePrice } from '../lib/api';

function renderWithLanguage(price: LivePrice) {
  return render(
    <LanguageProvider>
      <LivePriceReadout price={price} />
    </LanguageProvider>,
  );
}

describe('LivePriceReadout', () => {
  it('shows the price and a positive change badge', () => {
    renderWithLanguage({ ltp: 2530.5, change_pct: 1.2, as_of: '2026-07-15T09:30:00+00:00', available: true });
    expect(screen.getByText('₹2530.50')).toBeInTheDocument();
    expect(screen.getByText('+1.20%')).toBeInTheDocument();
  });

  it('shows a negative change badge in bearish styling', () => {
    renderWithLanguage({ ltp: 2470.0, change_pct: -1.2, as_of: '2026-07-15T09:30:00+00:00', available: true });
    expect(screen.getByText('-1.20%')).toHaveClass('text-bearish');
  });

  it('shows an "as of HH:MM:SS" timestamp derived from as_of', () => {
    renderWithLanguage({ ltp: 2530.5, change_pct: 1.2, as_of: '2026-07-15T09:30:00+00:00', available: true });
    expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument();
  });

  it('shows an unavailable message when available is false', () => {
    renderWithLanguage({ ltp: null, change_pct: null, as_of: null, available: false });
    expect(screen.getByText('Price unavailable right now.')).toBeInTheDocument();
  });
});
