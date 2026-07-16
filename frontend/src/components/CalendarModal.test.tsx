import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CalendarModal from './CalendarModal';
import * as api from '../lib/api';
import type { Alert } from '../lib/api';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider } from '../lib/language';

// Same IST computation CalendarModal itself uses, kept independent here so
// the test doesn't depend on the test runner's own local timezone -- picking
// the 1st of the current IST month guarantees a valid, always-present cell
// regardless of which month the suite happens to run in.
function currentIstMonthFirstDay(): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
  }).formatToParts(new Date());
  const year = parts.find((p) => p.type === 'year')?.value;
  const month = parts.find((p) => p.type === 'month')?.value;
  return `${year}-${month}-01`;
}

function makeAlert(id: number, title: string): Alert {
  return {
    id,
    category: 'oil_energy',
    category_label: 'oil_energy',
    created_at: '2026-07-01T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}`, image_url: null },
    companies: [],
  };
}

function renderModal(onClose = vi.fn()) {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <AuthProvider>
          <CalendarModal open onClose={onClose} />
        </AuthProvider>
      </LanguageProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('CalendarModal', () => {
  it('renders nothing when closed', () => {
    vi.spyOn(api, 'getCalendarCounts').mockResolvedValue({});
    render(
      <MemoryRouter>
        <LanguageProvider>
          <AuthProvider>
            <CalendarModal open={false} onClose={() => {}} />
          </AuthProvider>
        </LanguageProvider>
      </MemoryRouter>,
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('shows a count badge on days with news and disables days without', async () => {
    const dayKey = currentIstMonthFirstDay();
    vi.spyOn(api, 'getCalendarCounts').mockResolvedValue({ [dayKey]: 4 });

    renderModal();

    const dayOne = await screen.findByRole('button', { name: '1 4' });
    expect(dayOne).toBeEnabled();
    // Day 2 has no entry in the mocked counts response -- must be unclickable.
    expect(screen.getByRole('button', { name: '2' })).toBeDisabled();
  });

  it('drills into a day and lists its alerts, then opens one on click', async () => {
    const dayKey = currentIstMonthFirstDay();
    vi.spyOn(api, 'getCalendarCounts').mockResolvedValue({ [dayKey]: 2 });
    vi.spyOn(api, 'getCalendarDay').mockResolvedValue([
      makeAlert(1, 'First headline'),
      makeAlert(2, 'Second headline'),
    ]);

    renderModal();

    await userEvent.click(await screen.findByRole('button', { name: '1 2' }));

    expect(api.getCalendarDay).toHaveBeenCalledWith(dayKey, 'en');
    expect(await screen.findByText('First headline')).toBeInTheDocument();
    expect(screen.getByText('Second headline')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /first headline/i }));
    expect(await screen.findByText(/no affected companies/i)).toBeInTheDocument();
  });

  it('Escape closes only the topmost alert popup, not the whole calendar', async () => {
    const dayKey = currentIstMonthFirstDay();
    vi.spyOn(api, 'getCalendarCounts').mockResolvedValue({ [dayKey]: 1 });
    vi.spyOn(api, 'getCalendarDay').mockResolvedValue([makeAlert(1, 'Only headline')]);
    const onClose = vi.fn();

    renderModal(onClose);

    await userEvent.click(await screen.findByRole('button', { name: '1 1' }));
    await userEvent.click(await screen.findByRole('button', { name: /only headline/i }));
    expect(await screen.findByText(/no affected companies/i)).toBeInTheDocument();

    await userEvent.keyboard('{Escape}');

    // The alert popup closed...
    await waitFor(() => expect(screen.queryByText(/no affected companies/i)).not.toBeInTheDocument());
    // ...but the day view (and the calendar itself) stayed open -- this is
    // the regression case for the nested-AlertDetail Escape bug: both
    // AlertDetail instances' document keydown listeners used to fire on one
    // Escape press, closing the entire calendar instead of just the popup.
    expect(screen.getByText('Only headline')).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
