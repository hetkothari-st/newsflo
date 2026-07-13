import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import AlertCompanies from './AlertCompanies';
import type { Alert } from '../lib/api';

const alert: Alert = {
  id: 1,
  category: 'oil_energy',
  created_at: '2026-07-09T10:00:00+00:00',
  article: { id: 1, title: 'US strikes Iran oil export sites', url: 'https://example.com/a', image_url: null },
  companies: [
    {
      company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance Industries', index_tier: 'NIFTY50',
      direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'Refiner up.', key_points: [],
      basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN', in_my_holdings: true, past_mentions: [],
      sector: 'Energy',
    },
    {
      company_id: 2, ticker: 'ONGC.NS', name: 'ONGC', index_tier: 'NIFTYNEXT50',
      direction: 'bearish', magnitude_low: -3, magnitude_high: -1, rationale: 'Cost pressure.', key_points: [],
      basis: 'sector_inference', confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
      sector: 'Financials',
    },
  ],
};

describe('AlertCompanies', () => {
  it('shows Predicted companies grouped by tier by default', () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    expect(screen.getByText('Nifty 50')).toBeInTheDocument();
    expect(screen.getByText('Nifty Next 50')).toBeInTheDocument();
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.getByText('ONGC')).toBeInTheDocument();
  });

  it('filters to held companies on the My Portfolio tab', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    await userEvent.click(screen.getByRole('button', { name: /my portfolio/i }));
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.queryByText('ONGC')).not.toBeInTheDocument();
  });

  it('shows a login prompt on My Portfolio when logged out with no matches', async () => {
    const anon: Alert = { ...alert, companies: alert.companies.map((c) => ({ ...c, in_my_holdings: false })) };
    render(<AlertCompanies alert={anon} isAuthenticated={false} />);
    await userEvent.click(screen.getByRole('button', { name: /my portfolio/i }));
    expect(screen.getByText(/log in to see holdings-matched alerts/i)).toBeInTheDocument();
  });

  it('renders tier headings in Nifty 50 -> Next 50 -> Midcap 150 -> Smallcap 250 -> Global -> Other order', async () => {
    const tierAlert: Alert = {
      ...alert,
      companies: [
        { ...alert.companies[1], company_id: 1, name: 'Other Co', index_tier: 'OTHER' },
        { ...alert.companies[1], company_id: 2, name: 'Global Co', index_tier: 'GLOBAL_LARGE_CAP' },
        { ...alert.companies[0], company_id: 3, name: 'Fifty Co', index_tier: 'NIFTY50' },
        { ...alert.companies[1], company_id: 4, name: 'Next Fifty Co', index_tier: 'NIFTYNEXT50' },
        { ...alert.companies[1], company_id: 5, name: 'Midcap Co', index_tier: 'NIFTYMIDCAP150' },
        { ...alert.companies[1], company_id: 6, name: 'Smallcap Co', index_tier: 'NIFTYSMALLCAP250' },
      ],
    };
    render(<AlertCompanies alert={tierAlert} isAuthenticated />);
    const headings = screen.getAllByText(
      /^(Nifty 50|Nifty Next 50|Nifty Midcap 150|Nifty Smallcap 250|Global|Other)$/,
    );
    expect(headings.map((el) => el.textContent)).toEqual([
      'Nifty 50', 'Nifty Next 50', 'Nifty Midcap 150', 'Nifty Smallcap 250', 'Global', 'Other',
    ]);
  });

  it('shows Bullish/Bearish group headers with counts when grouped by Impact', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'impact');
    expect(screen.getByText('Bullish · 1')).toBeInTheDocument();
    expect(screen.getByText('Bearish · 1')).toBeInTheDocument();
  });

  it('shows sector group headers with counts when grouped by Sector', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'sector');
    expect(screen.getByText('Energy · 1')).toBeInTheDocument();
    expect(screen.getByText('Financials · 1')).toBeInTheDocument();
  });

  it('mutes sector-inferred companies relative to direct-mention companies when grouped', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'impact');
    expect(screen.getByText('Reliance Industries').closest('.opacity-70')).toBeNull();
    expect(screen.getByText('ONGC').closest('.opacity-70')).not.toBeNull();
  });

  it('shows the empty-state message instead of a blank panel when Impact mode has no groupable companies', async () => {
    const noDirectionAlert: Alert = {
      ...alert,
      companies: alert.companies.map((c) => ({ ...c, direction: 'unknown' })),
    };
    render(<AlertCompanies alert={noDirectionAlert} isAuthenticated />);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'impact');
    expect(screen.getByText('No affected companies for this story.')).toBeInTheDocument();
  });

  it('shows the sentiment bar reflecting the currently visible (tab-filtered) companies', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    expect(screen.getByText('1 Bullish')).toBeInTheDocument();
    expect(screen.getByText('1 Bearish')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /my portfolio/i }));
    expect(screen.getByText('1 Bullish')).toBeInTheDocument();
    expect(screen.getByText('0 Bearish')).toBeInTheDocument();
  });
});
