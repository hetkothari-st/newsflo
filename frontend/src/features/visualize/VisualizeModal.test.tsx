import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import VisualizeModal from './VisualizeModal';
import type { Alert } from '../../lib/api';

const alert: Alert = {
  id: 1, category: 'oil_energy', created_at: '2026-07-09T10:00:00+00:00',
  article: { id: 1, title: 'US strikes Iran oil export sites', url: 'https://example.com/a', image_url: null },
  companies: [
    {
      company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance Industries', index_tier: 'NIFTY50',
      direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'Refiner up.',
      key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
      in_my_holdings: true, past_mentions: [], sector: 'Energy',
    },
  ],
};

describe('VisualizeModal', () => {
  it('renders the article title and the impact tree by default', () => {
    render(<VisualizeModal alert={alert} onClose={() => {}} />);
    expect(screen.getAllByText('US strikes Iran oil export sites').length).toBeGreaterThan(0);
    expect(screen.getByText('Bullish')).toBeInTheDocument();
  });

  it('switches to the sector tree when picked', async () => {
    render(<VisualizeModal alert={alert} onClose={() => {}} />);
    await userEvent.click(screen.getByText('Sector Tree'));
    expect(screen.getByText('Energy')).toBeInTheDocument();
  });

  it('calls onClose when the close button is clicked', async () => {
    const onClose = vi.fn();
    render(<VisualizeModal alert={alert} onClose={onClose} />);
    await userEvent.click(screen.getByLabelText('Close'));
    expect(onClose).toHaveBeenCalled();
  });

  it('shows an empty-state message when the alert has no companies', () => {
    render(<VisualizeModal alert={{ ...alert, companies: [] }} onClose={() => {}} />);
    expect(screen.getByText('No affected companies for this story.')).toBeInTheDocument();
  });
});
