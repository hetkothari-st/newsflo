import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import LoginForm from './LoginForm';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';

function renderWithAuth(ui: ReactElement) {
  return render(<AuthProvider>{ui}</AuthProvider>);
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('LoginForm', () => {
  it('shows a validation error when fields are empty', async () => {
    renderWithAuth(<LoginForm />);
    await userEvent.click(screen.getByRole('button', { name: /log in/i }));
    expect(screen.getByRole('alert')).toHaveTextContent(/email and password/i);
  });

  it('stores a token in localStorage on successful login', async () => {
    vi.spyOn(api, 'login').mockResolvedValue({ access_token: 'tok-1', token_type: 'bearer' });
    const onSuccess = vi.fn();
    renderWithAuth(<LoginForm onSuccess={onSuccess} />);
    await userEvent.type(screen.getByLabelText(/email/i), 'a@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'pw12345');
    await userEvent.click(screen.getByRole('button', { name: /log in/i }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(localStorage.getItem('newsflo.token')).toBe('tok-1');
    expect(localStorage.getItem('newsflo.email')).toBe('a@example.com');
  });

  it('shows the backend error message on failed login', async () => {
    vi.spyOn(api, 'login').mockRejectedValue(new Error('Invalid email or password'));
    renderWithAuth(<LoginForm />);
    await userEvent.type(screen.getByLabelText(/email/i), 'a@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: /log in/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password');
  });
});
