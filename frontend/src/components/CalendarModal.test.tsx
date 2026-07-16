import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CalendarModal from './CalendarModal';
import * as api from '../lib/api';
import type { Alert, AlertCompany } from '../lib/api';
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

function makeAlert(id: number, title: string, companies: AlertCompany[] = []): Alert {
  return {
    id,
    category: 'oil_energy',
    category_label: 'oil_energy',
    created_at: '2026-07-01T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}`, image_url: null },
    companies,
  };
}

function makeCompany(companyId: number, name: string, sector: string): AlertCompany {
  return {
    company_id: companyId,
    ticker: `${name.toUpperCase()}.NS`,
    name,
    index_tier: 'NIFTY50',
    sector,
    direction: 'bullish',
    magnitude_low: 1,
    magnitude_high: 2,
    rationale: 'test',
    key_points: [],
    confidence_score: 50,
    time_horizon: 'Short-Term',
    basis: 'direct_mention',
    confidence: 'llm_estimate',
    market: 'IN',
    in_my_holdings: false,
    past_mentions: [],
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

  it('filters the day by sector, then by company, mutually exclusively', async () => {
    const dayKey = currentIstMonthFirstDay();
    vi.spyOn(api, 'getCalendarCounts').mockResolvedValue({ [dayKey]: 3 });
    vi.spyOn(api, 'getCalendarDay').mockResolvedValue([
      makeAlert(1, 'Banking headline', [makeCompany(1, 'HDFC Bank', 'banking')]),
      makeAlert(2, 'Oil headline', [makeCompany(2, 'Reliance', 'oil_gas')]),
      // Names HDFC Bank again (a different alert affecting the same
      // company), plus a second banking company -- exercises both the
      // "company" filter (id 1 should match this one too) and the
      // "sector" filter (banking should match this one too).
      makeAlert(3, 'Second banking headline', [
        makeCompany(1, 'HDFC Bank', 'banking'),
        makeCompany(3, 'ICICI Bank', 'banking'),
      ]),
    ]);

    renderModal();

    await userEvent.click(await screen.findByRole('button', { name: '1 3' }));
    expect(await screen.findByText('Banking headline')).toBeInTheDocument();
    expect(screen.getByText('Oil headline')).toBeInTheDocument();
    expect(screen.getByText('Second banking headline')).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText(/sector/i), 'banking');
    expect(screen.getByText('Banking headline')).toBeInTheDocument();
    expect(screen.getByText('Second banking headline')).toBeInTheDocument();
    expect(screen.queryByText('Oil headline')).not.toBeInTheDocument();

    // Picking a company resets the sector filter back to "all" -- the two
    // are mutually exclusive, not ANDed together.
    await userEvent.selectOptions(screen.getByLabelText(/company/i), '2');
    expect(screen.getByLabelText(/sector/i)).toHaveValue('all');
    expect(screen.getByText('Oil headline')).toBeInTheDocument();
    expect(screen.queryByText('Banking headline')).not.toBeInTheDocument();
    expect(screen.queryByText('Second banking headline')).not.toBeInTheDocument();

    // Company 1 (HDFC Bank) is named by two distinct alerts -- both, and
    // only those, must show up ("this company's news and news where it's
    // shown as affected" collapses to one membership check).
    await userEvent.selectOptions(screen.getByLabelText(/company/i), '1');
    expect(screen.getByText('Banking headline')).toBeInTheDocument();
    expect(screen.getByText('Second banking headline')).toBeInTheDocument();
    expect(screen.queryByText('Oil headline')).not.toBeInTheDocument();
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
