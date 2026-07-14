import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import AccountPage from './AccountPage';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider } from '../lib/language';
import { ThemeProvider } from '../lib/theme';
import * as api from '../lib/api';
import type { Profile } from '../lib/api';

const profile: Profile = {
  id: 1,
  email: 'me@example.com',
  created_at: '2026-01-15T00:00:00Z',
  email_alerts_enabled: true,
};

function renderPage(ui: ReactElement = <AccountPage />) {
  localStorage.setItem('newsflo.token', 'tok');
  localStorage.setItem('newsflo.email', 'me@example.com');
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <LanguageProvider>
          <AuthProvider>{ui}</AuthProvider>
        </LanguageProvider>
      </ThemeProvider>
    </MemoryRouter>,
  );
}

function mockWatchlistApis() {
  vi.spyOn(api, 'getCategories').mockResolvedValue([]);
  vi.spyOn(api, 'getCompanies').mockResolvedValue([]);
  vi.spyOn(api, 'getWatchlist').mockResolvedValue({ categories: [], companies: [] });
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  document.documentElement.classList.remove('light');
});

describe('AccountPage', () => {
  it('shows the profile email and member-since date', async () => {
    vi.spyOn(api, 'getMe').mockResolvedValue(profile);
    mockWatchlistApis();
    renderPage();
    expect(await screen.findByText('me@example.com')).toBeInTheDocument();
    expect(screen.getByText(/Jan 15, 2026/i)).toBeInTheDocument();
  });

  it('toggles email alerts', async () => {
    vi.spyOn(api, 'getMe').mockResolvedValue(profile);
    vi.spyOn(api, 'updatePreferences').mockResolvedValue({ ...profile, email_alerts_enabled: false });
    mockWatchlistApis();
    renderPage();
    const checkbox = await screen.findByRole('checkbox', { name: /email alerts/i });
    await userEvent.click(checkbox);
    await waitFor(() =>
      expect(api.updatePreferences).toHaveBeenCalledWith('tok', false),
    );
  });

  it('changes password successfully', async () => {
    vi.spyOn(api, 'getMe').mockResolvedValue(profile);
    vi.spyOn(api, 'changePassword').mockResolvedValue(undefined);
    mockWatchlistApis();
    renderPage();
    await screen.findByText('me@example.com');
    await userEvent.type(screen.getByLabelText(/current password/i), 'oldpass1');
    await userEvent.type(screen.getByLabelText(/new password/i), 'newpass2');
    await userEvent.click(screen.getByRole('button', { name: /update password/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/password updated/i);
  });

  it('shows an error when password change fails', async () => {
    vi.spyOn(api, 'getMe').mockResolvedValue(profile);
    vi.spyOn(api, 'changePassword').mockRejectedValue(new Error('Current password is incorrect'));
    mockWatchlistApis();
    renderPage();
    await screen.findByText('me@example.com');
    await userEvent.type(screen.getByLabelText(/current password/i), 'wrong');
    await userEvent.type(screen.getByLabelText(/new password/i), 'newpass2');
    await userEvent.click(screen.getByRole('button', { name: /update password/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Current password is incorrect');
  });

  it('deletes the account after confirming with a password', async () => {
    vi.spyOn(api, 'getMe').mockResolvedValue(profile);
    vi.spyOn(api, 'deleteAccount').mockResolvedValue(undefined);
    mockWatchlistApis();
    renderPage();
    await screen.findByText('me@example.com');
    await userEvent.click(screen.getByRole('button', { name: /^delete account$/i }));
    await userEvent.type(screen.getByLabelText(/enter your password to confirm/i), 'mypass1');
    await userEvent.click(screen.getByRole('button', { name: /delete my account/i }));
    await waitFor(() => expect(api.deleteAccount).toHaveBeenCalledWith('tok', 'mypass1'));
    expect(localStorage.getItem('newsflo.token')).toBeNull();
  });

  it('renders the watchlist settings form', async () => {
    vi.spyOn(api, 'getMe').mockResolvedValue(profile);
    mockWatchlistApis();
    renderPage();
    expect(await screen.findByRole('form', { name: /custom filters/i })).toBeInTheDocument();
  });
});
