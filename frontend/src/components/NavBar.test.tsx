import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import NavBar from './NavBar';
import { AuthProvider } from '../lib/auth';

function renderNav() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <NavBar />
      </AuthProvider>
    </MemoryRouter>,
  );
}

afterEach(() => localStorage.clear());

describe('NavBar', () => {
  it('shows Login and Register when logged out', () => {
    renderNav();
    expect(screen.getByRole('link', { name: /login/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /register/i })).toBeInTheDocument();
  });

  it('shows the user email and a Logout button when logged in', () => {
    localStorage.setItem('newsflo.token', 'tok');
    localStorage.setItem('newsflo.email', 'me@example.com');
    renderNav();
    expect(screen.getByText('me@example.com')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /logout/i })).toBeInTheDocument();
  });
});
