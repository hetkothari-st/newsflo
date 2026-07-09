import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import AlertCard from './AlertCard';
import type { Alert } from '../lib/api';

const alert: Alert = {
  id: 1,
  category: 'oil_energy',
  created_at: '2026-07-09T10:00:00+00:00',
  article: { id: 1, title: 'US strikes Iran oil export sites', url: 'https://example.com/a' },
  companies: [
    {
      company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance Industries', index_tier: 'NIFTY50',
      direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'Refiner up.',
      basis: 'direct_mention', confidence: 'llm_estimate', in_my_holdings: true,
    },
    {
      company_id: 2, ticker: 'ONGC.NS', name: 'ONGC', index_tier: 'NIFTY100',
      direction: 'bearish', magnitude_low: -3, magnitude_high: -1, rationale: 'Cost pressure.',
      basis: 'sector_inference', confidence: 'llm_estimate', in_my_holdings: false,
    },
  ],
};

describe('AlertCard', () => {
  it('renders the serif headline and is collapsed by default', () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    expect(screen.getByText('US strikes Iran oil export sites')).toBeInTheDocument();
    // Chips are hidden until the card is expanded.
    expect(screen.queryByText('Reliance Industries')).not.toBeInTheDocument();
  });

  it('expands to show tier-grouped chips on headline click', async () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    await userEvent.click(screen.getByText('US strikes Iran oil export sites'));
    expect(screen.getByText('Nifty 50')).toBeInTheDocument();
    expect(screen.getByText('Nifty 100')).toBeInTheDocument();
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.getByText('ONGC')).toBeInTheDocument();
  });

  it('filters to held companies only on the My Demat tab', async () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    await userEvent.click(screen.getByRole('button', { name: /my demat/i }));
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.queryByText('ONGC')).not.toBeInTheDocument();
  });

  it('shows the login prompt on My Demat when logged out and nothing matches', async () => {
    const anon: Alert = { ...alert, companies: alert.companies.map((c) => ({ ...c, in_my_holdings: false })) };
    render(<AlertCard alert={anon} isAuthenticated={false} />);
    await userEvent.click(screen.getByRole('button', { name: /my demat/i }));
    expect(screen.getByText(/log in to see holdings-matched alerts/i)).toBeInTheDocument();
  });

  it('shows an empty-holdings message on My Demat when logged in with no matches', async () => {
    const noneHeld: Alert = { ...alert, companies: alert.companies.map((c) => ({ ...c, in_my_holdings: false })) };
    render(<AlertCard alert={noneHeld} isAuthenticated />);
    await userEvent.click(screen.getByRole('button', { name: /my demat/i }));
    expect(screen.getByText(/none of your holdings are affected/i)).toBeInTheDocument();
  });

  it('shows a Mixed net-sentiment pill on the Predicted tab (1 bullish, 1 bearish)', () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    expect(screen.getByText('Mixed')).toBeInTheDocument();
  });
});
