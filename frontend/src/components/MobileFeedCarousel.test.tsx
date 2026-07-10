import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import MobileFeedCarousel from './MobileFeedCarousel';
import type { Alert } from '../lib/api';

function makeAlert(id: number, title: string): Alert {
  return {
    id,
    category: 'oil_energy',
    created_at: '2026-07-09T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}`, image_url: null },
    companies: [],
  };
}

describe('MobileFeedCarousel', () => {
  it('renders one card per alert', () => {
    render(<MobileFeedCarousel alerts={[makeAlert(1, 'First'), makeAlert(2, 'Second')]} onOpen={() => {}} />);
    expect(screen.getByText('First')).toBeInTheDocument();
    expect(screen.getByText('Second')).toBeInTheDocument();
  });

  it('calls onOpen with the alert id when a card is clicked', async () => {
    const onOpen = vi.fn();
    render(<MobileFeedCarousel alerts={[makeAlert(7, 'Seventh')]} onOpen={onOpen} />);
    await userEvent.click(screen.getByRole('button', { name: /seventh/i }));
    expect(onOpen).toHaveBeenCalledWith(7);
  });
});
