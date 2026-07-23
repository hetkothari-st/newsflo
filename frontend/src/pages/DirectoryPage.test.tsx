import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DirectoryPage from './DirectoryPage';
import * as feedV2Api from '../lib/feedV2Api';
import type { DirectoryCompany } from '../lib/feedV2Api';
import { AuthProvider } from '../lib/auth';

function renderPage() {
  return render(
    <AuthProvider>
      <MemoryRouter>
        <DirectoryPage />
      </MemoryRouter>
    </AuthProvider>,
  );
}

function makeCompanies(): DirectoryCompany[] {
  return [
    { ticker: 'RELIANCE.NS', name: 'Reliance Industries', sector: 'oil_gas', cap_tier: 'LARGE' },
    { ticker: 'SOMETEXTILE.NS', name: 'Demo Textiles Ltd', sector: 'textiles', cap_tier: 'SMALL' },
  ];
}

describe('DirectoryPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders companies with ticker, name, sector, and cap tier', async () => {
    vi.spyOn(feedV2Api, 'getDirectory').mockResolvedValue(makeCompanies());
    renderPage();

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    // Scoped to <span> because the cap-tier <select> also renders an
    // <option>LARGE</option> / <option>SMALL</option> with identical text.
    expect(screen.getByText('LARGE', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByText('Demo Textiles Ltd')).toBeInTheDocument();
    expect(screen.getByText('SMALL', { selector: 'span' })).toBeInTheDocument();
  });

  it('re-fetches with the selected cap tier filter', async () => {
    const spy = vi.spyOn(feedV2Api, 'getDirectory').mockResolvedValue(makeCompanies());
    renderPage();
    await waitFor(() => expect(spy).toHaveBeenCalledWith({}, null));

    fireEvent.change(screen.getByLabelText('Cap tier'), { target: { value: 'LARGE' } });

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ capTier: 'LARGE' }, null));
  });

  it('re-fetches with the selected sector filter', async () => {
    const spy = vi.spyOn(feedV2Api, 'getDirectory').mockResolvedValue(makeCompanies());
    renderPage();
    await waitFor(() => expect(spy).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText('Sector'), { target: { value: 'oil_gas' } });

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ sector: 'oil_gas' }, null));
  });

  it('links each row to its stock deep-dive with no alertId', async () => {
    vi.spyOn(feedV2Api, 'getDirectory').mockResolvedValue(makeCompanies());
    renderPage();

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    const link = screen.getByRole('link', { name: /Reliance Industries/ });
    expect(link).toHaveAttribute('href', '/feed-v2/stock/RELIANCE.NS');
  });
});
