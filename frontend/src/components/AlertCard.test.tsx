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
      basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN', in_my_holdings: true,
    },
    {
      company_id: 2, ticker: 'ONGC.NS', name: 'ONGC', index_tier: 'NIFTY100',
      direction: 'bearish', magnitude_low: -3, magnitude_high: -1, rationale: 'Cost pressure.',
      basis: 'sector_inference', confidence: 'llm_estimate', market: 'IN', in_my_holdings: false,
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

  it('filters to held companies only on the My Portfolio tab', async () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    await userEvent.click(screen.getByRole('button', { name: /my portfolio/i }));
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.queryByText('ONGC')).not.toBeInTheDocument();
  });

  it('shows the login prompt on My Portfolio when logged out and nothing matches', async () => {
    const anon: Alert = { ...alert, companies: alert.companies.map((c) => ({ ...c, in_my_holdings: false })) };
    render(<AlertCard alert={anon} isAuthenticated={false} />);
    await userEvent.click(screen.getByRole('button', { name: /my portfolio/i }));
    expect(screen.getByText(/log in to see holdings-matched alerts/i)).toBeInTheDocument();
  });

  it('shows an empty-holdings message on My Portfolio when logged in with no matches', async () => {
    const noneHeld: Alert = { ...alert, companies: alert.companies.map((c) => ({ ...c, in_my_holdings: false })) };
    render(<AlertCard alert={noneHeld} isAuthenticated />);
    await userEvent.click(screen.getByRole('button', { name: /my portfolio/i }));
    expect(screen.getByText(/none of your holdings are affected/i)).toBeInTheDocument();
  });

  it('shows a Mixed net-sentiment pill on the Predicted tab (1 bullish, 1 bearish)', () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    expect(screen.getByText('Mixed')).toBeInTheDocument();
  });

  it('recomputes the sentiment pill when switching tabs to a different majority direction', async () => {
    // Predicted (all companies): 2 bullish, 1 bearish -> majority bullish -> "Net Bullish".
    // My Portfolio (only held companies): the single held company is bearish -> "Net Bearish".
    const mixedDirectionAlert: Alert = {
      ...alert,
      companies: [
        { ...alert.companies[0], company_id: 1, direction: 'bullish', in_my_holdings: false },
        { ...alert.companies[0], company_id: 2, direction: 'bullish', in_my_holdings: false },
        { ...alert.companies[1], company_id: 3, direction: 'bearish', in_my_holdings: true },
      ],
    };
    render(<AlertCard alert={mixedDirectionAlert} isAuthenticated />);
    await userEvent.click(screen.getByText('US strikes Iran oil export sites'));

    expect(screen.getByText('Net Bullish')).toBeInTheDocument();
    expect(screen.queryByText('Net Bearish')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /my portfolio/i }));

    expect(screen.getByText('Net Bearish')).toBeInTheDocument();
    expect(screen.queryByText('Net Bullish')).not.toBeInTheDocument();
  });

  it('renders tier group headings in Nifty 50 -> Nifty 100 -> Nifty 500 -> Other order', async () => {
    // Companies are listed out of tier order in the source data to prove the
    // component re-orders them rather than merely preserving input order.
    const tierAlert: Alert = {
      ...alert,
      companies: [
        { ...alert.companies[1], company_id: 1, name: 'Other Co', index_tier: 'SMALLCAP' },
        { ...alert.companies[1], company_id: 2, name: 'Five Hundred Co', index_tier: 'NIFTY500' },
        { ...alert.companies[0], company_id: 3, name: 'Fifty Co', index_tier: 'NIFTY50' },
        { ...alert.companies[1], company_id: 4, name: 'Hundred Co', index_tier: 'NIFTY100' },
      ],
    };
    render(<AlertCard alert={tierAlert} isAuthenticated />);
    await userEvent.click(screen.getByText('US strikes Iran oil export sites'));

    const headings = screen.getAllByText(/^(Nifty 50|Nifty 100|Nifty 500|Other)$/);
    expect(headings.map((el) => el.textContent)).toEqual(['Nifty 50', 'Nifty 100', 'Nifty 500', 'Other']);
  });

  it('expands the card on Enter when the header is focused', async () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    const header = screen.getByRole('button', { name: /us strikes iran/i });
    header.focus();
    expect(screen.queryByText('Reliance Industries')).not.toBeInTheDocument();
    await userEvent.keyboard('{Enter}');
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
  });

  it('expands the card on Space when the header is focused', async () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    const header = screen.getByRole('button', { name: /us strikes iran/i });
    header.focus();
    expect(screen.queryByText('Reliance Industries')).not.toBeInTheDocument();
    await userEvent.keyboard('{ }');
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
  });

  it('opens the visualize modal from the expanded card', async () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    await userEvent.click(screen.getByText('US strikes Iran oil export sites'));
    await userEvent.click(screen.getByRole('button', { name: /visualize/i }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('closes the visualize modal without collapsing the card', async () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    await userEvent.click(screen.getByText('US strikes Iran oil export sites'));
    await userEvent.click(screen.getByRole('button', { name: /visualize/i }));
    await userEvent.click(screen.getByLabelText('Close'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
  });
});
