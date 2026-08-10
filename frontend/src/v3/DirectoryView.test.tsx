import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DirectoryView from './DirectoryView';
import { AuthProvider } from '../lib/auth';
import type { DirectoryCompany } from './api';

const COMPANIES: DirectoryCompany[] = [
  {
    ticker: 'RELIANCE.NS',
    name: 'Reliance Industries',
    sector: 'oil_gas',
    cap_tier: 'LARGE',
    logo_url: null,
    market_cap: 17_662_582_622_436,
    index_tier: 'NIFTY50',
    sub_sector: 'refining_marketing',
    pe: 44.9,
    pb: 3.2,
    roe: 15.0,
  },
  {
    ticker: 'TCS.NS',
    name: 'Tata Consultancy Services',
    sector: 'it',
    cap_tier: 'LARGE',
    logo_url: null,
    market_cap: 12_000_000_000_000,
    index_tier: 'NIFTY50',
    sub_sector: 'services',
    pe: 28.1,
    pb: 11.0,
    roe: 46.0,
  },
  {
    ticker: 'SMALLCO.NS',
    name: 'Small Widgets',
    sector: 'it',
    cap_tier: 'SMALL',
    logo_url: null,
    market_cap: 9_000_000_000,
    index_tier: 'OTHER',
    sub_sector: null,
    pe: null,
    pb: null,
    roe: null,
  },
];

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) =>
        Promise.resolve({ ok: true, status: 200, json: async () => body } as unknown as Response);
      if (url.includes('/api/feed-v2/directory')) return json(COMPANIES);
      return json([]);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

function renderDirectory(onOpenDeepDive = vi.fn()) {
  render(
    <MemoryRouter>
      <AuthProvider>
        <DirectoryView active onOpenDeepDive={onOpenDeepDive} />
      </AuthProvider>
    </MemoryRouter>,
  );
  return onOpenDeepDive;
}

describe('DirectoryView', () => {
  it('renders all companies with market cap, PE and index badge', async () => {
    renderDirectory();
    await screen.findByText('Reliance Industries');
    expect(screen.getByText('Tata Consultancy Services')).toBeInTheDocument();
    // 17,662,582,622,436 rupees -> 17,66,258 crore (en-IN grouping).
    expect(screen.getByText('₹17,66,258 Cr')).toBeInTheDocument();
    expect(screen.getByText('PE 44.9')).toBeInTheDocument();
    // Null PE renders a dash, never zero.
    expect(screen.getByText('PE —')).toBeInTheDocument();
    // NIFTY50 badge on two rows; OTHER gets none.
    expect(screen.getAllByText('N50')).toHaveLength(2);
    expect(screen.queryByText('OTHER')).not.toBeInTheDocument();
  });

  it('search narrows by name or ticker', async () => {
    renderDirectory();
    await screen.findByText('Reliance Industries');
    fireEvent.change(screen.getByLabelText('Search directory'), { target: { value: 'tcs' } });
    expect(screen.getByText('Tata Consultancy Services')).toBeInTheDocument();
    expect(screen.queryByText('Reliance Industries')).not.toBeInTheDocument();
  });

  it('sub-sector dropdown appears only after choosing a sector and narrows', async () => {
    renderDirectory();
    await screen.findByText('Reliance Industries');
    expect(screen.queryByLabelText('Sub-sector filter')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Sector filter'), { target: { value: 'it' } });
    const subSelect = await screen.findByLabelText('Sub-sector filter');
    fireEvent.change(subSelect, { target: { value: 'services' } });
    expect(screen.getByText('Tata Consultancy Services')).toBeInTheDocument();
    // Null sub_sector drops out when a specific sub-sector is chosen.
    expect(screen.queryByText('Small Widgets')).not.toBeInTheDocument();
  });

  it('PE range hides companies without PE data', async () => {
    renderDirectory();
    await screen.findByText('Reliance Industries');
    fireEvent.click(screen.getByRole('button', { name: /advanced/i }));
    fireEvent.change(screen.getByLabelText('PE min'), { target: { value: '30' } });
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.queryByText('Tata Consultancy Services')).not.toBeInTheDocument();
    expect(screen.queryByText('Small Widgets')).not.toBeInTheDocument();
  });

  it('sort by market cap reorders rows', async () => {
    renderDirectory();
    await screen.findByText('Reliance Industries');
    fireEvent.change(screen.getByLabelText('Sort directory'), {
      target: { value: 'market_cap_desc' },
    });
    const names = screen.getAllByText(/Reliance Industries|Tata Consultancy Services|Small Widgets/);
    expect(names.map((el) => el.textContent)).toEqual([
      'Reliance Industries',
      'Tata Consultancy Services',
      'Small Widgets',
    ]);
  });

  it('empty result shows the no-match message', async () => {
    renderDirectory();
    await screen.findByText('Reliance Industries');
    fireEvent.change(screen.getByLabelText('Search directory'), { target: { value: 'zzz' } });
    await waitFor(() =>
      expect(screen.getByText('No companies match these filters.')).toBeInTheDocument(),
    );
  });

  it('row click opens the deep dive', async () => {
    const onOpen = renderDirectory();
    await screen.findByText('Reliance Industries');
    fireEvent.click(screen.getByText('Reliance Industries'));
    expect(onOpen).toHaveBeenCalledWith('RELIANCE.NS');
  });
});
