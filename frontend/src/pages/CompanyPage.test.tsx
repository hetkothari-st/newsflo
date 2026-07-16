import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CompanyPage from './CompanyPage';
import { LanguageProvider } from '../lib/language';
import * as api from '../lib/api';
import type { CompanyProfile } from '../lib/api';

const baseProfile: CompanyProfile = {
  id: 1,
  ticker: 'RELIANCE.NS',
  name: 'Reliance Industries',
  sector: 'oil_gas',
  index_tier: 'NIFTY50',
  market: 'IN',
  isin: null,
  logo_url: null,
  latest_alert: null,
  track_record: null,
};

function renderPage(path = '/company/1') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <LanguageProvider>
        <Routes>
          <Route path="/company/:id" element={<CompanyPage />} />
        </Routes>
      </LanguageProvider>
    </MemoryRouter>,
  );
}

function mockHistoryAndPrices() {
  vi.spyOn(api, 'getCompanyHistory').mockResolvedValue({ mentions: [], has_more: false });
  vi.spyOn(api, 'getCompanyPrices').mockResolvedValue({ period: '6mo', points: [], available: false });
  vi.spyOn(api, 'getCompanyLivePrice').mockResolvedValue({ ltp: null, change_pct: null, as_of: null, available: false });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('CompanyPage', () => {
  it('shows the company name and ticker once the profile loads', async () => {
    vi.spyOn(api, 'getCompanyProfile').mockResolvedValue(baseProfile);
    mockHistoryAndPrices();
    renderPage();
    expect(await screen.findByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.getByText(/RELIANCE\.NS/)).toBeInTheDocument();
  });

  it('shows a not-found message when the profile resolves null', async () => {
    vi.spyOn(api, 'getCompanyProfile').mockResolvedValue(null);
    mockHistoryAndPrices();
    renderPage();
    expect(await screen.findByText('Company not found.')).toBeInTheDocument();
  });

  it('shows the latest alert headline signal when present', async () => {
    vi.spyOn(api, 'getCompanyProfile').mockResolvedValue({
      ...baseProfile,
      latest_alert: {
        alert_id: 5, created_at: '2026-07-01T00:00:00+00:00', direction: 'bullish',
        rationale: 'Margins expand on crude softening.', key_points: ['Crude eases, margins widen'],
        confidence: 'llm_estimate', category: 'oil_energy', category_label: 'Oil & Energy',
        article: { id: 1, title: 'Crude prices ease', url: 'https://example.com/a', image_url: null },
      },
    });
    mockHistoryAndPrices();
    renderPage();
    expect(await screen.findByText('Crude eases, margins widen')).toBeInTheDocument();
  });

  it('shows a no-alerts message when latest_alert is null', async () => {
    vi.spyOn(api, 'getCompanyProfile').mockResolvedValue(baseProfile);
    mockHistoryAndPrices();
    renderPage();
    expect(await screen.findByText('No news has affected this company yet.')).toBeInTheDocument();
  });

  it('shows a track-record-insufficient message when track_record is null', async () => {
    vi.spyOn(api, 'getCompanyProfile').mockResolvedValue(baseProfile);
    mockHistoryAndPrices();
    renderPage();
    expect(await screen.findByText('Not enough history yet to show a track record.')).toBeInTheDocument();
  });

  it('shows per-horizon win rates when track_record is present', async () => {
    vi.spyOn(api, 'getCompanyProfile').mockResolvedValue({
      ...baseProfile,
      track_record: { '1': { win_rate: 0.8, sample_size: 5 } },
    });
    mockHistoryAndPrices();
    renderPage();
    expect(await screen.findByText(/1-day win rate: 80% \(5 samples\)/)).toBeInTheDocument();
  });

  it('renders history mentions and loads more on click', async () => {
    vi.spyOn(api, 'getCompanyProfile').mockResolvedValue(baseProfile);
    vi.spyOn(api, 'getCompanyHistory')
      .mockResolvedValueOnce({
        mentions: [{
          alert_id: 1, article_title: 'First story', article_url: 'https://example.com/1',
          created_at: '2026-07-01T00:00:00+00:00', direction: 'bullish', category: 'oil_energy',
        }],
        has_more: true,
      })
      .mockResolvedValueOnce({
        mentions: [{
          alert_id: 2, article_title: 'Second story', article_url: 'https://example.com/2',
          created_at: '2026-06-01T00:00:00+00:00', direction: 'bearish', category: 'oil_energy',
        }],
        has_more: false,
      });
    vi.spyOn(api, 'getCompanyPrices').mockResolvedValue({ period: '6mo', points: [], available: false });
    renderPage();

    expect(await screen.findByText('First story')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /load more/i }));
    expect(await screen.findByText('Second story')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('button', { name: /load more/i })).not.toBeInTheDocument());
  });

  it('shows an error message when the profile fails to load', async () => {
    vi.spyOn(api, 'getCompanyProfile').mockRejectedValue(new Error('network down'));
    mockHistoryAndPrices();
    renderPage();
    expect(await screen.findByText('Could not load this company.')).toBeInTheDocument();
  });

  it('shows an inline error when history fails to load', async () => {
    vi.spyOn(api, 'getCompanyProfile').mockResolvedValue(baseProfile);
    vi.spyOn(api, 'getCompanyHistory').mockRejectedValue(new Error('network down'));
    vi.spyOn(api, 'getCompanyPrices').mockResolvedValue({ period: '6mo', points: [], available: false });
    renderPage();
    expect(await screen.findByText('Could not load news history.')).toBeInTheDocument();
  });

  it('shows an inline error when prices fail to load', async () => {
    vi.spyOn(api, 'getCompanyProfile').mockResolvedValue(baseProfile);
    vi.spyOn(api, 'getCompanyHistory').mockResolvedValue({ mentions: [], has_more: false });
    vi.spyOn(api, 'getCompanyPrices').mockRejectedValue(new Error('network down'));
    renderPage();
    expect(await screen.findByText('Could not load the price chart.')).toBeInTheDocument();
  });

  it('refetches prices when a different period is selected', async () => {
    vi.spyOn(api, 'getCompanyProfile').mockResolvedValue(baseProfile);
    vi.spyOn(api, 'getCompanyHistory').mockResolvedValue({ mentions: [], has_more: false });
    const pricesSpy = vi.spyOn(api, 'getCompanyPrices').mockResolvedValue({ period: '6mo', points: [], available: false });
    renderPage();

    await screen.findByText('Reliance Industries');
    await userEvent.click(screen.getByRole('button', { name: '1Y' }));
    expect(pricesSpy).toHaveBeenLastCalledWith(1, '1y');
  });

  it('shows the live price readout once it loads, and polls again after 3s', async () => {
    vi.spyOn(api, 'getCompanyProfile').mockResolvedValue(baseProfile);
    vi.spyOn(api, 'getCompanyHistory').mockResolvedValue({ mentions: [], has_more: false });
    vi.spyOn(api, 'getCompanyPrices').mockResolvedValue({ period: '6mo', points: [{ date: '2026-07-14', close: 2500 }], available: true });
    const liveSpy = vi.spyOn(api, 'getCompanyLivePrice').mockResolvedValue({
      ltp: 2530, change_pct: 1.2, as_of: '2026-07-15T09:30:00+00:00', available: true,
    });

    // Fake timers are installed *before* rendering so the effect's
    // setInterval is itself a fake timer -- a real setInterval created
    // before vi.useFakeTimers() is never adopted by the fake clock, so
    // advancing later would silently never fire it (confirmed by hand).
    vi.useFakeTimers();
    renderPage();
    // Flush the initial mount's pending promises without relying on
    // findByText/waitFor, which poll via setTimeout and would hang under
    // fake timers -- advancing by 0ms still drains the microtask queue.
    // Wrapped in act() so the resulting setState is treated as part of a
    // tracked React update rather than firing a "not wrapped in act" warning.
    await act(() => vi.advanceTimersByTimeAsync(0));

    expect(screen.getByText('₹2530.00')).toBeInTheDocument();
    expect(liveSpy).toHaveBeenCalledTimes(1);

    // advanceTimersByTimeAsync also flushes the microtask queue as it
    // advances, so the mocked promise from the second poll() call resolves
    // within this same await instead of needing a separate waitFor.
    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(liveSpy).toHaveBeenCalledTimes(2);

    vi.useRealTimers();
  });

  it("appends today's live price as the chart's last point when the historical series ends before today", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-15T10:00:00Z'));
    vi.spyOn(api, 'getCompanyProfile').mockResolvedValue(baseProfile);
    vi.spyOn(api, 'getCompanyHistory').mockResolvedValue({ mentions: [], has_more: false });
    vi.spyOn(api, 'getCompanyPrices').mockResolvedValue({ period: '6mo', points: [{ date: '2026-07-14', close: 2500 }], available: true });
    vi.spyOn(api, 'getCompanyLivePrice').mockResolvedValue({
      ltp: 2530, change_pct: 1.2, as_of: '2026-07-15T09:30:00+00:00', available: true,
    });

    renderPage();
    // Flush the initial mount's pending promises without relying on
    // findByText/waitFor, which poll via setTimeout and would hang under
    // fake timers -- advancing by 0ms still drains the microtask queue.
    // Wrapped in act() so the resulting setState is treated as part of a
    // tracked React update rather than firing a "not wrapped in act" warning.
    await act(() => vi.advanceTimersByTimeAsync(0));

    expect(screen.getByText('₹2530.00')).toBeInTheDocument();
    // Historical series ends 2026-07-14; system time is 2026-07-15, so
    // withLivePoint must have appended (not replaced) a new point --
    // 2500 -> 2530 reads as bullish only if that append happened.
    expect(screen.getByRole('img', { name: /price chart, bullish/i })).toBeInTheDocument();

    vi.useRealTimers();
  });
});
