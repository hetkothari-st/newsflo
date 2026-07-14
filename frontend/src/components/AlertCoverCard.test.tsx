import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import AlertCoverCard from './AlertCoverCard';
import type { Alert } from '../lib/api';
import { LanguageProvider } from '../lib/language';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderWithLanguage(ui: ReactElement) {
  return render(
    <MemoryRouter>
      <LanguageProvider>{ui}</LanguageProvider>
    </MemoryRouter>,
  );
}

// Mirrors the raw dispatchEvent pattern in useHorizontalSwipe.test.tsx --
// touchstart at fromX, then touchend carrying changedTouches at toX, both
// with a fixed y so the gesture reads as purely horizontal.
function fireTouchSwipe(target: Element, { fromX, toX }: { fromX: number; toX: number }) {
  target.dispatchEvent(
    Object.assign(new Event('touchstart', { bubbles: true }), { touches: [{ clientX: fromX, clientY: 0 }] }),
  );
  target.dispatchEvent(
    Object.assign(new Event('touchend', { bubbles: true }), { changedTouches: [{ clientX: toX, clientY: 0 }] }),
  );
}

const alert: Alert = {
  id: 1,
  category: 'oil_energy',
  category_label: 'oil_energy',
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
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  it('renders the headline, category, and sentiment', () => {
    renderWithLanguage(<AlertCoverCard alert={alert} onOpen={() => {}} variant="carousel" />);
    expect(screen.getByText('US strikes Iran oil export sites')).toBeInTheDocument();
    expect(screen.getByText('Oil & Energy')).toBeInTheDocument();
    expect(screen.getByText('Net Bullish')).toBeInTheDocument();
  });

  it('calls onOpen when clicked', async () => {
    const onOpen = vi.fn();
    renderWithLanguage(<AlertCoverCard alert={alert} onOpen={onOpen} variant="carousel" />);
    await userEvent.click(screen.getByRole('button', { name: /us strikes iran/i }));
    expect(onOpen).toHaveBeenCalled();
  });

  it('calls onOpen on Enter when focused', async () => {
    const onOpen = vi.fn();
    renderWithLanguage(<AlertCoverCard alert={alert} onOpen={onOpen} variant="grid" />);
    const card = screen.getByRole('button', { name: /us strikes iran/i });
    card.focus();
    await userEvent.keyboard('{Enter}');
    expect(onOpen).toHaveBeenCalled();
  });

  it('clamps the grid variant headline so a long title can never overflow the fixed-aspect tile', () => {
    const longTitle =
      'A very long headline that would otherwise wrap across many lines and grow taller than the narrow fixed-aspect grid tile can hold';
    renderWithLanguage(
      <AlertCoverCard
        alert={{ ...alert, article: { ...alert.article, title: longTitle } }}
        onOpen={() => {}}
        variant="grid"
      />,
    );
    expect(screen.getByText(longTitle)).toHaveClass('line-clamp-3');
  });

  it('clamps the carousel variant headline too, with more room for a longer title', () => {
    renderWithLanguage(<AlertCoverCard alert={alert} onOpen={() => {}} variant="carousel" />);
    expect(screen.getByText('US strikes Iran oil export sites')).toHaveClass('line-clamp-4');
  });

  it('gets a raised shadow in light mode', () => {
    renderWithLanguage(<AlertCoverCard alert={alert} onOpen={() => {}} variant="grid" />);
    expect(screen.getByRole('button', { name: /us strikes iran/i })).toHaveClass('theme-light:shadow-neu');
  });

  it('navigates to the charts page on a right swipe (collapsed card)', () => {
    renderWithLanguage(<AlertCoverCard alert={alert} onOpen={vi.fn()} variant="carousel" />);
    const card = screen.getByRole('button');
    fireTouchSwipe(card, { fromX: 0, toX: 100 });
    expect(mockNavigate).toHaveBeenCalledWith(`/alerts/${alert.id}/charts`);
  });

  it('navigates to the charts page on a right swipe (expanded card)', () => {
    renderWithLanguage(
      <AlertCoverCard alert={alert} onOpen={vi.fn()} variant="carousel" expanded onClose={vi.fn()} isAuthenticated />,
    );
    const card = screen.getByLabelText('Close').closest('div.relative.flex') as HTMLElement;
    expect(card).not.toBeNull();
    fireTouchSwipe(card, { fromX: 0, toX: 100 });
    expect(mockNavigate).toHaveBeenCalledWith(`/alerts/${alert.id}/charts`);
  });

  it('does not navigate on a right swipe for the grid variant (desktop-only, no touch entry)', () => {
    renderWithLanguage(<AlertCoverCard alert={alert} onOpen={vi.fn()} variant="grid" />);
    const card = screen.getByRole('button');
    fireTouchSwipe(card, { fromX: 0, toX: 100 });
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
