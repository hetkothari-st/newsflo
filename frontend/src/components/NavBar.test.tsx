import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import NavBar from './NavBar';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider } from '../lib/language';
import { ThemeProvider } from '../lib/theme';

function renderNav() {
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <LanguageProvider>
          <AuthProvider>
            <NavBar onOpenCalendar={() => {}} />
          </AuthProvider>
        </LanguageProvider>
      </ThemeProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove('light');
});

describe('NavBar', () => {
  it('shows Login and Register when logged out', () => {
    renderNav();
    expect(screen.getByRole('link', { name: /login/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /register/i })).toBeInTheDocument();
  });

  it('links to /account when logged in', () => {
    localStorage.setItem('newsflo.token', 'tok');
    localStorage.setItem('newsflo.email', 'me@example.com');
    renderNav();
    expect(screen.getByRole('link', { name: /account/i })).toHaveAttribute('href', '/account');
  });

  it('renders the theme toggle', () => {
    renderNav();
    expect(screen.getByRole('button', { name: /switch to light mode/i })).toBeInTheDocument();
  });
});
