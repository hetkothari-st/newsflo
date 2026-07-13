import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import BottomNav from './BottomNav';
import { AuthProvider } from '../lib/auth';
import { ThemeProvider } from '../lib/theme';

function renderNav(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ThemeProvider>
        <AuthProvider>
          <BottomNav />
        </AuthProvider>
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

  it('opens an account sheet with email, the theme toggle, and Logout when logged in', async () => {
    setToken();
    renderNav();
    await userEvent.click(screen.getByRole('button', { name: /account/i }));
    expect(screen.getByText('a@example.com')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /switch to light mode/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /logout/i })).toBeInTheDocument();
  });

  it('calls logout and closes the sheet when Logout is clicked', async () => {
    setToken();
    renderNav();
    await userEvent.click(screen.getByRole('button', { name: /account/i }));
    await userEvent.click(screen.getByRole('button', { name: /logout/i }));
    expect(screen.queryByText('a@example.com')).not.toBeInTheDocument();
  });
});
