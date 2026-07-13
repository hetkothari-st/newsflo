import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import HoldingsForm from './HoldingsForm';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider } from '../lib/language';
import * as api from '../lib/api';

function setToken() {
  localStorage.setItem('newsflo.token', 'tok');
  localStorage.setItem('newsflo.email', 'a@example.com');
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('HoldingsForm', () => {
  it('validates ticker and a positive quantity', async () => {
    setToken();
    render(
      <LanguageProvider>
        <AuthProvider>
          <HoldingsForm onAdded={() => {}} />
        </AuthProvider>
      </LanguageProvider>,
    );
    await userEvent.click(screen.getByRole('button', { name: /add/i }));
    expect(screen.getByRole('alert')).toHaveTextContent(/ticker and a positive quantity/i);
  });

  it('adds a holding and calls onAdded', async () => {
    setToken();
    const spy = vi
      .spyOn(api, 'addHolding')
      .mockResolvedValue({ company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance', quantity: 5 });
    const onAdded = vi.fn();
    render(
      <LanguageProvider>
        <AuthProvider>
          <HoldingsForm onAdded={onAdded} />
        </AuthProvider>
      </LanguageProvider>,
    );
    await userEvent.type(screen.getByLabelText(/ticker/i), 'RELIANCE.NS');
    await userEvent.type(screen.getByLabelText(/quantity/i), '5');
    await userEvent.click(screen.getByRole('button', { name: /add/i }));
    await waitFor(() => expect(onAdded).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith('tok', 'RELIANCE.NS', 5);
  });
});
