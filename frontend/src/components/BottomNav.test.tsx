import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import BottomNav from './BottomNav';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider } from '../lib/language';
import { ThemeProvider } from '../lib/theme';

function renderNav(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ThemeProvider>
        <LanguageProvider>
          <AuthProvider>
            <BottomNav />
          </AuthProvider>
        </LanguageProvider>
      </ThemeProvider>
    </MemoryRouter>,
  );
}

function setToken() {
  localStorage.setItem('newsflo.token', 'tok');
  localStorage.setItem('newsflo.email', 'a@example.com');
}

afterEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove('light');
});

describe('BottomNav', () => {
  it('renders Feed and Holdings links', () => {
    renderNav();
    expect(screen.getByRole('link', { name: /^feed$/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /^holdings$/i })).toBeInTheDocument();
  });

  it('links Account to /login when logged out', () => {
    renderNav();
    expect(screen.getByRole('link', { name: /account/i })).toHaveAttribute('href', '/login');
  });

  it('links Account to /account when logged in', () => {
    setToken();
    renderNav();
    expect(screen.getByRole('link', { name: /account/i })).toHaveAttribute('href', '/account');
  });
});
