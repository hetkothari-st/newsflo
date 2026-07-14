import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import MobileFeedCarousel from './MobileFeedCarousel';
import type { Alert } from '../lib/api';
import { LanguageProvider } from '../lib/language';

function makeAlert(id: number, title: string): Alert {
  return {
    id,
    category: 'oil_energy',
    category_label: 'oil_energy',
    created_at: '2026-07-09T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}`, image_url: null },
    companies: [],
  };
}

describe('MobileFeedCarousel', () => {
  it('renders one card per alert', () => {
    render(
      <MemoryRouter>
        <LanguageProvider>
          <MobileFeedCarousel alerts={[makeAlert(1, 'First'), makeAlert(2, 'Second')]} onOpen={() => {}} />
        </LanguageProvider>
      </MemoryRouter>,
    );
    expect(screen.getByText('First')).toBeInTheDocument();
    expect(screen.getByText('Second')).toBeInTheDocument();
  });

  it('calls onOpen with the alert id when a card is clicked', async () => {
    const onOpen = vi.fn();
    render(
      <MemoryRouter>
        <LanguageProvider>
          <MobileFeedCarousel alerts={[makeAlert(7, 'Seventh')]} onOpen={onOpen} />
        </LanguageProvider>
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole('button', { name: /seventh/i }));
    expect(onOpen).toHaveBeenCalledWith(7);
  });
});
