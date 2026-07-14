import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Feed, { dedupeByTitle, mergeAlerts } from './Feed';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider, useLanguage } from '../lib/language';
import * as api from '../lib/api';
import type { Alert, AlertCompany } from '../lib/api';

// Isolate Feed from the real socket in most tests; individual tests override
// this via vi.mocked(useAlertsSocket).mockReturnValue(...) where needed.
vi.mock('../lib/useAlertsSocket', () => ({ useAlertsSocket: vi.fn(() => ({ alerts: [], connected: true })) }));
import { useAlertsSocket } from '../lib/useAlertsSocket';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1,
    ticker: 'RELIANCE.NS',
    name: 'Reliance',
    index_tier: 'NIFTY50',
    direction: 'bullish',
    magnitude_low: 1,
    magnitude_high: 2,
    rationale: 'x',
    key_points: [],
    basis: 'direct_mention',
    confidence: 'llm_estimate',
    market: 'IN',
    in_my_holdings: false,
    past_mentions: [],
    ...overrides,
  };
}

function makeAlert(id: number, title: string, companies: AlertCompany[], category = 'oil_energy'): Alert {
  return {
    id,
    category,
    category_label: category,
    created_at: '2026-07-10T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}`, image_url: null },
    companies,
  };
}

function renderFeed() {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <AuthProvider>
          <Feed />
        </AuthProvider>
      </LanguageProvider>
    </MemoryRouter>,
  );
}

function LanguageSwitchHarness() {
  const { setLanguage } = useLanguage();
  return (
    <>
      <button type="button" onClick={() => setLanguage('hi')}>
        switch language
      </button>
      <Feed />
    </>
  );
}

function renderFeedWithLanguageControl() {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <AuthProvider>
          <LanguageSwitchHarness />
        </AuthProvider>
      </LanguageProvider>
    </MemoryRouter>,
  );
}

function setToken() {
  localStorage.setItem('newsflo.token', 'tok');
  localStorage.setItem('newsflo.email', 'a@example.com');
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.mocked(useAlertsSocket).mockReturnValue({ alerts: [], connected: true });
  localStorage.clear();
});

describe('mergeAlerts', () => {
  it('prepends live alerts and dedupes by id (fetched data wins on collision)', () => {
    const merged = mergeAlerts([makeAlert(2, 'two-live', [])], [makeAlert(1, 'one', []), makeAlert(2, 'two', [])]);
    expect(merged.map((a) => a.id)).toEqual([2, 1]);
    expect(merged[0].article.title).toBe('two');
  });
});

describe('dedupeByTitle', () => {
  it('keeps only the first (newest) alert per normalized article title', () => {
    const first = makeAlert(10, 'Q1 surprise sends jewellery stocks shining 40%', []);
    const second = makeAlert(9, '  Q1 SURPRISE sends jewellery stocks shining 40%  ', []);
    const other = makeAlert(8, 'Unrelated headline', []);
    expect(dedupeByTitle([first, second, other]).map((a) => a.id)).toEqual([10, 8]);
  });
});

describe('Feed', () => {
  const indiaAlert = makeAlert(1, 'India oil headline', [company({ market: 'IN' })]);
  const globalAlert = makeAlert(2, 'Global tech headline', [
    company({ company_id: 2, ticker: 'AAPL', name: 'Apple', market: 'GLOBAL' }),
  ], 'it');

  it('defaults to the India tab and switches to Global on click', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert, globalAlert]);
    renderFeed();
    // Both the mobile carousel and desktop grid render a card per alert (CSS
    // toggles which is visible; jsdom doesn't evaluate media queries), so
    // each title matches twice -- assert on the count rather than a single element.
    expect((await screen.findAllByText('India oil headline')).length).toBeGreaterThan(0);
    expect(screen.queryAllByText('Global tech headline')).toHaveLength(0);

    await userEvent.click(screen.getByRole('tab', { name: /global/i }));
    expect((await screen.findAllByText('Global tech headline')).length).toBeGreaterThan(0);
    expect(screen.queryAllByText('India oil headline')).toHaveLength(0);
  });

  it('automatically refetches once a language-switch translation drain finishes, without a page reload', async () => {
    const englishAlert = makeAlert(1, 'English title', [company({ market: 'IN' })]);
    const translatedAlert = makeAlert(1, 'हिन्दी शीर्षक', [company({ market: 'IN' })]);
    const getAlertsSpy = vi
      .spyOn(api, 'getAlerts')
      .mockResolvedValueOnce([englishAlert]) // initial mount fetch (lang=en)
      .mockResolvedValueOnce([englishAlert]) // fetch the language switch itself already triggers -- translation isn't ready yet
      .mockResolvedValueOnce([translatedAlert]); // the silent refetch once the drain completes -- what this test targets
    vi.spyOn(api, 'triggerTranslation').mockResolvedValue({ started: true });
    vi.spyOn(api, 'getTranslationStatus').mockResolvedValue({ total: 1, translated: 1, running: false });

    renderFeedWithLanguageControl();
    await screen.findAllByText('English title');

    await userEvent.click(screen.getByRole('button', { name: 'switch language' }));

    expect((await screen.findAllByText('हिन्दी शीर्षक')).length).toBeGreaterThan(0);
    expect(screen.queryAllByText('English title')).toHaveLength(0);
    expect(getAlertsSpy).toHaveBeenCalledTimes(3);
  });

  it('desktop: opens AlertDetail with the company breakdown when the grid card is clicked', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    renderFeed();
    await screen.findAllByText('India oil headline');
    // Both the mobile carousel and desktop grid render a card for this alert
    // (CSS toggles which is visible; jsdom doesn't evaluate media queries).
    // Mobile is rendered first (see Feed.tsx's `body`), so index 1 is the grid card.
    const cards = screen.getAllByRole('button', { name: /india oil headline/i });
    await userEvent.click(cards[1]);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    // openAlertId is shared state, so the mobile card (still mounted, CSS
    // -hidden only in a real browser) expands inline too -- assert presence,
    // not a single match.
    expect(screen.getAllByText('Reliance').length).toBeGreaterThan(0);
  });

  it('mobile: expands the company breakdown inline in the card, with a close button', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    renderFeed();
    await screen.findAllByText('India oil headline');
    const cards = screen.getAllByRole('button', { name: /india oil headline/i });
    await userEvent.click(cards[0]); // mobile carousel card
    // AlertDetail's desktop dialog is CSS-hidden on mobile (see
    // hiddenOnMobile) but still mounted -- jsdom doesn't evaluate media
    // queries, so this only asserts the inline copy the mobile card itself
    // renders, not the absence of the desktop one.
    expect(screen.getAllByText('Reliance').length).toBeGreaterThan(0);
    // Two Close buttons mount: the mobile card's own, plus the (CSS-hidden
    // on mobile, jsdom doesn't evaluate that) desktop AlertDetail's.
    expect(screen.getAllByRole('button', { name: /close/i }).length).toBeGreaterThan(0);
  });

  it('Custom tab shows a login prompt when logged out', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    renderFeed();
    await userEvent.click(screen.getByRole('tab', { name: /custom/i }));
    expect(await screen.findByText(/log in to build your custom feed/i)).toBeInTheDocument();
  });

  it('Custom tab settings gear opens the filter editor in a sheet', async () => {
    setToken();
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ categories: [], companies: [] });
    vi.spyOn(api, 'getCategories').mockResolvedValue([]);
    vi.spyOn(api, 'getCompanies').mockResolvedValue([]);
    renderFeed();
    await userEvent.click(screen.getByRole('tab', { name: /custom/i }));
    await userEvent.click(await screen.findByLabelText(/custom feed settings/i));
    expect(await screen.findByRole('button', { name: /save/i })).toBeInTheDocument();
  });

  it('queues a live-pushed alert as "N new" instead of splicing it in immediately', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    vi.mocked(useAlertsSocket).mockReturnValue({ alerts: [], connected: true });
    const { rerender } = renderFeed();
    await screen.findAllByText('India oil headline');

    const liveAlert = makeAlert(3, 'Live oil headline', [company({ company_id: 3, market: 'IN' })]);
    vi.mocked(useAlertsSocket).mockReturnValue({ alerts: [liveAlert], connected: true });
    rerender(
      <MemoryRouter>
        <LanguageProvider>
          <AuthProvider>
            <Feed />
          </AuthProvider>
        </LanguageProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText('1 new')).toBeInTheDocument();
    expect(screen.queryAllByText('Live oil headline')).toHaveLength(0);

    await userEvent.click(screen.getByText('1 new'));
    // Same carousel/grid duplication as above -- assert on the count.
    expect((await screen.findAllByText('Live oil headline')).length).toBeGreaterThan(0);
    expect(screen.queryByText('1 new')).not.toBeInTheDocument();
  });

  it('does not count a live alert on a market the user is not viewing', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    vi.mocked(useAlertsSocket).mockReturnValue({ alerts: [], connected: true });
    const { rerender } = renderFeed();
    await screen.findAllByText('India oil headline');

    // User is on the India tab (default); a live GLOBAL alert arrives.
    const liveGlobalAlert = makeAlert(4, 'Live global headline', [
      company({ company_id: 4, ticker: 'MSFT', name: 'Microsoft', market: 'GLOBAL' }),
    ], 'it');
    vi.mocked(useAlertsSocket).mockReturnValue({ alerts: [liveGlobalAlert], connected: true });
    rerender(
      <MemoryRouter>
        <LanguageProvider>
          <AuthProvider>
            <Feed />
          </AuthProvider>
        </LanguageProvider>
      </MemoryRouter>,
    );

    // The India tab must not show a misleading "new" pill for a Global-only alert.
    expect(screen.queryByText('1 new')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: /global/i }));
    expect((await screen.findAllByText('Live global headline')).length).toBeGreaterThan(0);
  });

  it('scrolls the carousel and window to top when "N new" is revealed', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    vi.mocked(useAlertsSocket).mockReturnValue({ alerts: [], connected: true });
    const { rerender } = renderFeed();
    await screen.findAllByText('India oil headline');

    const liveAlert = makeAlert(5, 'Another live headline', [company({ company_id: 5, market: 'IN' })]);
    vi.mocked(useAlertsSocket).mockReturnValue({ alerts: [liveAlert], connected: true });
    rerender(
      <MemoryRouter>
        <LanguageProvider>
          <AuthProvider>
            <Feed />
          </AuthProvider>
        </LanguageProvider>
      </MemoryRouter>,
    );
    await screen.findByText('1 new');

    const scrollToSpy = vi.fn();
    HTMLElement.prototype.scrollTo = scrollToSpy;
    const windowScrollToSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});

    await userEvent.click(screen.getByText('1 new'));

    expect(scrollToSpy).toHaveBeenCalledWith({ top: 0 });
    expect(windowScrollToSpy).toHaveBeenCalledWith({ top: 0 });
  });

  it('scrolls to top on tab switch, so a residual scroll offset never carries a stale position into the new tab', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert, globalAlert]);
    renderFeed();
    await screen.findAllByText('India oil headline');

    const scrollToSpy = vi.fn();
    HTMLElement.prototype.scrollTo = scrollToSpy;
    const windowScrollToSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});

    await userEvent.click(screen.getByRole('tab', { name: /global/i }));

    expect(scrollToSpy).toHaveBeenCalledWith({ top: 0 });
    expect(windowScrollToSpy).toHaveBeenCalledWith({ top: 0 });
  });
});
