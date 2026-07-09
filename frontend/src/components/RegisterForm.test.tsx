import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import RegisterForm from './RegisterForm';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';

function renderWithAuth(ui: ReactElement) {
  return render(<AuthProvider>{ui}</AuthProvider>);
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('RegisterForm', () => {
  it('rejects a password shorter than 6 characters', async () => {
    renderWithAuth(<RegisterForm />);
    await userEvent.type(screen.getByLabelText(/email/i), 'a@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'short');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));
    expect(screen.getByRole('alert')).toHaveTextContent(/at least 6 characters/i);
  });

  it('stores a token on successful registration', async () => {
    vi.spyOn(api, 'register').mockResolvedValue({ access_token: 'tok-9', token_type: 'bearer' });
    const onSuccess = vi.fn();
    renderWithAuth(<RegisterForm onSuccess={onSuccess} />);
    await userEvent.type(screen.getByLabelText(/email/i), 'new@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'pw12345');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(localStorage.getItem('newsflo.token')).toBe('tok-9');
  });

  it('shows the backend error message on a duplicate email', async () => {
    vi.spyOn(api, 'register').mockRejectedValue(new Error('Email already registered'));
    renderWithAuth(<RegisterForm />);
    await userEvent.type(screen.getByLabelText(/email/i), 'dup@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'pw12345');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Email already registered');
  });
});
