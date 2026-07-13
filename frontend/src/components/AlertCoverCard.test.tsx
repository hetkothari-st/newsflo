import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import AlertCoverCard from './AlertCoverCard';
import type { Alert } from '../lib/api';

const alert: Alert = {
  id: 1,
  category: 'oil_energy',
  created_at: '2026-07-09T10:00:00+00:00',
  article: { id: 1, title: 'US strikes Iran oil export sites', url: 'https://example.com/a', image_url: 'https://example.com/pic.jpg' },
  companies: [
    {
      company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance Industries', index_tier: 'NIFTY50',
      direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'x', key_points: [],
      basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
    },
  ],
};

describe('AlertCoverCard', () => {
  it('renders the headline, category, and sentiment', () => {
    render(<AlertCoverCard alert={alert} onOpen={() => {}} variant="carousel" />);
    expect(screen.getByText('US strikes Iran oil export sites')).toBeInTheDocument();
    expect(screen.getByText('Oil & Energy')).toBeInTheDocument();
    expect(screen.getByText('Net Bullish')).toBeInTheDocument();
  });

  it('calls onOpen when clicked', async () => {
    const onOpen = vi.fn();
    render(<AlertCoverCard alert={alert} onOpen={onOpen} variant="carousel" />);
    await userEvent.click(screen.getByRole('button', { name: /us strikes iran/i }));
    expect(onOpen).toHaveBeenCalled();
  });

  it('calls onOpen on Enter when focused', async () => {
    const onOpen = vi.fn();
    render(<AlertCoverCard alert={alert} onOpen={onOpen} variant="grid" />);
    const card = screen.getByRole('button', { name: /us strikes iran/i });
    card.focus();
    await userEvent.keyboard('{Enter}');
    expect(onOpen).toHaveBeenCalled();
  });

  it('clamps the grid variant headline so a long title can never overflow the fixed-aspect tile', () => {
    const longTitle =
      'A very long headline that would otherwise wrap across many lines and grow taller than the narrow fixed-aspect grid tile can hold';
    render(
      <AlertCoverCard
        alert={{ ...alert, article: { ...alert.article, title: longTitle } }}
        onOpen={() => {}}
        variant="grid"
      />,
    );
    expect(screen.getByText(longTitle)).toHaveClass('line-clamp-3');
  });

  it('clamps the carousel variant headline too, with more room for a longer title', () => {
    render(<AlertCoverCard alert={alert} onOpen={() => {}} variant="carousel" />);
    expect(screen.getByText('US strikes Iran oil export sites')).toHaveClass('line-clamp-4');
  });
});
