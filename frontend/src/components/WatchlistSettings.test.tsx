import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import WatchlistSettings from './WatchlistSettings';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider } from '../lib/language';
import * as api from '../lib/api';
import type { Company, Watchlist } from '../lib/api';

const companies: Company[] = [
  { id: 1, ticker: 'AAPL', name: 'Apple', sector: 'it', index_tier: 'GLOBAL_LARGE_CAP', market: 'GLOBAL', isin: null, logo_url: null },
  { id: 2, ticker: 'RELIANCE.NS', name: 'Reliance', sector: 'oil_gas', index_tier: 'NIFTY50', market: 'IN', isin: null, logo_url: null },
];

function setToken() {
  localStorage.setItem('newsflo.token', 'tok');
  localStorage.setItem('newsflo.email', 'a@example.com');
}

function mockApis(watchlist: Watchlist) {
  vi.spyOn(api, 'getCategories').mockResolvedValue([
    { category: 'banking', label: 'banking' },
    { category: 'oil_energy', label: 'oil_energy' },
  ]);
  vi.spyOn(api, 'getCompanies').mockResolvedValue(companies);
  vi.spyOn(api, 'getWatchlist').mockResolvedValue(watchlist);
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('WatchlistSettings', () => {
  it('renders categories and companies from the API', async () => {
    setToken();
    mockApis({ categories: [], companies: [] });
    render(
      <LanguageProvider>
        <AuthProvider>
          <WatchlistSettings />
        </AuthProvider>
      </LanguageProvider>,
    );
    expect(await screen.findByLabelText('oil_energy')).toBeInTheDocument();
    expect(screen.getByLabelText('banking')).toBeInTheDocument();
    expect(screen.getByLabelText(/Apple/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Reliance/)).toBeInTheDocument();
  });

  it('pre-checks boxes from the existing watchlist', async () => {
    setToken();
    mockApis({ categories: ['oil_energy'], companies: [{ company_id: 1, ticker: 'AAPL', name: 'Apple' }] });
    render(
      <LanguageProvider>
        <AuthProvider>
          <WatchlistSettings />
        </AuthProvider>
      </LanguageProvider>,
    );
    expect(await screen.findByLabelText('oil_energy')).toBeChecked();
    expect(screen.getByLabelText('banking')).not.toBeChecked();
    expect(screen.getByLabelText(/Apple/)).toBeChecked();
    expect(screen.getByLabelText(/Reliance/)).not.toBeChecked();
  });

  it('saves the selected category and company via putWatchlist', async () => {
    setToken();
    mockApis({ categories: [], companies: [] });
    const put = vi
      .spyOn(api, 'putWatchlist')
      .mockResolvedValue({ categories: ['oil_energy'], companies: [{ company_id: 1, ticker: 'AAPL', name: 'Apple' }] });
    render(
      <LanguageProvider>
        <AuthProvider>
          <WatchlistSettings />
        </AuthProvider>
      </LanguageProvider>,
    );
    await userEvent.click(await screen.findByLabelText('oil_energy'));
    await userEvent.click(screen.getByLabelText(/Apple/));
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(put).toHaveBeenCalledWith('tok', ['oil_energy'], [1]));
    expect(await screen.findByRole('alert')).toHaveTextContent(/saved/i);
  });

  it('keeps the selected company row\'s dark-mode background unchanged, tinting only in light mode', async () => {
    setToken();
    mockApis({ categories: [], companies: [{ company_id: 1, ticker: 'AAPL', name: 'Apple' }] });
    render(
      <LanguageProvider>
        <AuthProvider>
          <WatchlistSettings />
        </AuthProvider>
      </LanguageProvider>,
    );
    const row = (await screen.findByLabelText(/Apple/)).closest('label');
    expect(row).toHaveClass('bg-hairline/40', 'theme-light:bg-accent/10');
  });

  it('filters the company list by the text input', async () => {
    setToken();
    mockApis({ categories: [], companies: [] });
    render(
      <LanguageProvider>
        <AuthProvider>
          <WatchlistSettings />
        </AuthProvider>
      </LanguageProvider>,
    );
    await screen.findByLabelText(/Apple/);
    await userEvent.type(screen.getByLabelText(/filter companies/i), 'relian');
    expect(screen.getByLabelText(/Reliance/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Apple/)).not.toBeInTheDocument();
  });
});
