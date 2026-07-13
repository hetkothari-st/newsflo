import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import HoldingsPage from './HoldingsPage';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider } from '../lib/language';
import * as api from '../lib/api';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('HoldingsPage', () => {
  it('fetches and lists the user holdings on mount', async () => {
    localStorage.setItem('newsflo.token', 'tok');
    localStorage.setItem('newsflo.email', 'a@example.com');
    vi.spyOn(api, 'getHoldings').mockResolvedValue([
      { company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance', quantity: 3 },
    ]);
    render(
      <LanguageProvider>
        <AuthProvider>
          <HoldingsPage />
        </AuthProvider>
      </LanguageProvider>,
    );
    expect(await screen.findByText('Reliance')).toBeInTheDocument();
  });
});
