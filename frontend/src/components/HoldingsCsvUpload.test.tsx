import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import HoldingsCsvUpload from './HoldingsCsvUpload';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider } from '../lib/language';
import * as api from '../lib/api';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('HoldingsCsvUpload', () => {
  it('uploads a selected CSV file and reports the loaded count', async () => {
    localStorage.setItem('newsflo.token', 'tok');
    localStorage.setItem('newsflo.email', 'a@example.com');
    const spy = vi.spyOn(api, 'uploadHoldingsCsv').mockResolvedValue({ loaded: 2 });
    const onUploaded = vi.fn();
    render(
      <LanguageProvider>
        <AuthProvider>
          <HoldingsCsvUpload onUploaded={onUploaded} />
        </AuthProvider>
      </LanguageProvider>,
    );
    const file = new File(['Ticker,Quantity\nRELIANCE.NS,10\n'], 'holdings.csv', { type: 'text/csv' });
    await userEvent.upload(screen.getByLabelText(/upload holdings csv/i), file);
    await waitFor(() => expect(onUploaded).toHaveBeenCalled());
    expect(spy).toHaveBeenCalled();
    expect(screen.getByText(/loaded 2 holdings/i)).toBeInTheDocument();
  });
});
