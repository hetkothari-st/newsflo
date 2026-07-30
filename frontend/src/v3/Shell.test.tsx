import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Shell from './Shell';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider } from '../lib/language';
import { ThemeProvider } from '../lib/theme';

const FEED_ALERT = {
  id: 7,
  category: 'oil_gas',
  category_label: null,
  created_at: '2026-07-29T05:32:00+00:00',
  summary_short: 'Cheaper crude helps users, hurts producers.',
  summary_long: 'Long summary.',
  article: {
    id: 1,
    image_url: 'https://example.com/news.jpg',
    title: 'Crude oil slips below $70 as OPEC+ signals higher output',
    url: 'https://example.com/a',
    source: 'Reuters',
    published_at: '2026-07-29T05:30:00+00:00',
  },
  excess_move_pct: -2.4,
  direction: 'bearish',
  raw_move_pct: -2.4,
  sector_move_pct: 0.0,
  volume_multiple: 2.6,
  benchmark_ticker: '^CNXENERGY',
  is_fallback_benchmark: false,
  peak_ticker: 'ONGC.NS',
  peak_company_name: 'ONGC',
  peak_cap_tier: 'LARGE',
  verdict: 'SECTOR_WIDE',
  intensity: { score: 71, band: 'Moderate', components: [] },
  breadth_score: 40,
  in_my_holdings: true,
};

const ALERT_DETAIL = {
  ...FEED_ALERT,
  layers: [
    {
      title: 'Losers — directly affected',
      relationship: 'DIRECT',
      icon: 'lose',
      note: 'They sell crude; a price fall cuts realisations.',
      rows: [
        {
          ticker: 'ONGC.NS',
          name: 'Oil & Natural Gas Corp',
          sector: 'oil_gas',
          cap_tier: 'LARGE',
          liquidity_tier: 'HIGH',
          delivery_pct: 68,
          business_desc: 'Explores and produces crude oil.',
          direction: 'bearish',
          excess_move_pct: -2.4,
          intensity: {
            score: 71,
            band: 'Moderate',
            components: [
              { label: 'excess', raw: -2.4, score: 66, weight: 0.31, contribution: 20.5 },
            ],
          },
          is_exposure_only: false,
          in_my_holdings: true,
          why: 'Lower oil prices cut its realisations directly.',
          logo_url: null,
        },
        {
          ticker: 'CHENNPETRO.NS',
          name: 'Chennai Petroleum',
          sector: 'oil_gas',
          cap_tier: 'MICRO',
          liquidity_tier: 'LOW',
          delivery_pct: 38,
          business_desc: 'A standalone refiner.',
          direction: 'bullish',
          excess_move_pct: 4.7,
          intensity: { score: 83, band: 'High', components: [] },
          is_exposure_only: false,
          in_my_holdings: false,
          why: 'Cheaper crude lifts refining margins.',
          logo_url: null,
        },
      ],
    },
  ],
  timeline: [{ horizon: 'TODAY', description: 'Producers reprice fast on 2.6× volume.' }],
};

const DEEP_DIVE = {
  ticker: 'CHENNPETRO.NS',
  name: 'Chennai Petroleum',
  sector: 'oil_gas',
  cap_tier: 'MICRO',
  business_desc: 'A standalone refiner turning crude into fuels.',
  logo_url: null,
  market_cap: 400,
  pe: 6.4,
  in_my_holdings: false,
  excess_move_pct: 4.7,
  raw_move_pct: 5.9,
  sector_move_pct: 1.2,
  volume_multiple: 4.1,
  liquidity_tier: 'LOW',
  delivery_pct: 38,
  intensity: {
    score: 83,
    band: 'High',
    components: [
      { label: 'excess', raw: 4.7, score: 88, weight: 0.31, contribution: 27.3 },
      { label: 'materiality', raw: 0.09, score: 91, weight: 0.28, contribution: 25.5 },
    ],
  },
  is_exposure_only: false,
  peers: [],
};

function mockFetch() {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    const json = (body: unknown) =>
      Promise.resolve({ ok: true, status: 200, json: async () => body } as unknown as Response);
    if (url.includes('/api/feed-v2/stock/')) return json(DEEP_DIVE);
    if (url.includes('/api/feed-v2/discovery/')) return json([]);
    if (url.includes('/api/feed-v2/directory')) return json([]);
    if (url.match(/\/api\/feed-v2\/\d+$/)) return json(ALERT_DETAIL);
    if (url.includes('/api/feed-v2')) return json([FEED_ALERT]);
    if (url.includes('/api/car-review')) return json([]);
    return json([]);
  });
}

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch());
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

function renderShell() {
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <LanguageProvider>
          <AuthProvider>
            <Shell />
          </AuthProvider>
        </LanguageProvider>
      </ThemeProvider>
    </MemoryRouter>,
  );
}

describe('Shell card feed', () => {
  it('renders the card front skim layer: excess move, verdict, headline, gist, held dot', async () => {
    renderShell();
    // The headline renders on both card faces (front + condensed back head).
    expect((await screen.findAllByText(/crude oil slips below \$70/i)).length).toBe(2);
    expect(screen.getByText('▼ 2.4%')).toBeInTheDocument();
    expect(screen.getByText('excess vs sector')).toBeInTheDocument();
    expect(screen.getByText('Sector-wide')).toBeInTheDocument();
    expect(screen.getByText('Cheaper crude helps users, hurts producers.')).toBeInTheDocument();
    expect(screen.getByText('held')).toBeInTheDocument();
    expect(screen.getByText("See who's affected")).toBeInTheDocument();
    // News image renders on the card front when the article has one.
    const front = screen.getByTestId('front-7');
    expect(front.querySelector('.nimg img')).toHaveAttribute('src', 'https://example.com/news.jpg');
  });

  it('falls back to category artwork when the article has no photo', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        const body =
          url.match(/\/api\/feed-v2$/) !== null
            ? [{ ...FEED_ALERT, article: { ...FEED_ALERT.article, image_url: null } }]
            : [];
        return Promise.resolve({ ok: true, status: 200, json: async () => body } as unknown as Response);
      }),
    );
    renderShell();
    const front = await screen.findByTestId('front-7');
    // Curated thematic art for the alert's category (oil_gas), not the
    // story's own photo -- publishers that block scraping still get a visual.
    expect(front.querySelector('.nimg img')?.getAttribute('src')).toContain('images.unsplash.com');
  });

  it('flips to the layered ripple on card tap and shows stock rows with tags + warnings', async () => {
    renderShell();
    fireEvent.click(await screen.findByTestId('front-7'));
    expect(await screen.findByText('Losers — directly affected')).toBeInTheDocument();
    expect(screen.getByText('They sell crude; a price fall cuts realisations.')).toBeInTheDocument();
    expect(screen.getByText('ONGC.NS')).toBeInTheDocument();
    expect(screen.getByText('CHENNPETRO.NS')).toBeInTheDocument();
    // Scoped to the micro cap's own row -- the always-mounted Directory
    // legend also contains a MICRO tag.
    expect(within(screen.getByTestId('srow-CHENNPETRO.NS')).getByText('MICRO')).toBeInTheDocument();
    // Low-delivery warning fires for the 38% delivery micro cap.
    expect(screen.getByText(/38% delivery — much of this move was intraday/i)).toBeInTheDocument();
    // Company logo (initials fallback -- no logo art in the fixture) on
    // every stock row.
    expect(within(screen.getByTestId('srow-ONGC.NS')).getByTestId('clogo-ONGC.NS')).toHaveTextContent(
      'ON',
    );
    // Compliance footer (spec §9).
    expect(
      screen.getByText(/intensity measures how hard the news hit — not whether a stock is good to own/i),
    ).toBeInTheDocument();
  });

  it('switches to the timeline tab on the card back', async () => {
    renderShell();
    fireEvent.click(await screen.findByTestId('front-7'));
    await screen.findByText('ONGC.NS');
    fireEvent.click(screen.getByRole('button', { name: 'Timeline' }));
    expect(await screen.findByText(/producers reprice fast/i)).toBeInTheDocument();
    expect(screen.getByText('Today')).toBeInTheDocument();
  });

  it('opens the deep-dive sheet from a stock row with score, signals and warnings', async () => {
    renderShell();
    fireEvent.click(await screen.findByTestId('front-7'));
    fireEvent.click(await screen.findByTestId('srow-CHENNPETRO.NS'));
    const sheet = within(screen.getByTestId('sheet'));
    expect(await sheet.findByText('High intensity')).toBeInTheDocument();
    expect(sheet.getByText(/how this score is built/i)).toBeInTheDocument();
    expect(sheet.getByText('Materiality')).toBeInTheDocument();
    expect(sheet.getByText(/only 38% of volume went to delivery/i)).toBeInTheDocument();
    expect(sheet.getByText(/small size and thin trading amplify moves/i)).toBeInTheDocument();
    expect(sheet.getByText(/not whether it's a good investment/i)).toBeInTheDocument();
  });

  it('opens the (i) glance popup without opening the deep dive', async () => {
    renderShell();
    fireEvent.click(await screen.findByTestId('front-7'));
    fireEvent.click(await screen.findByLabelText('About ONGC.NS'));
    expect(await screen.findByText('What they do')).toBeInTheDocument();
    expect(screen.getByText('Explores and produces crude oil.')).toBeInTheDocument();
    expect(screen.getByText(/glance view/i)).toBeInTheDocument();
    // Deep-dive-only content must NOT be present -- (i) = glance and stay.
    expect(screen.queryByText(/how this score is built/i)).not.toBeInTheDocument();
  });

  it('filters the feed by cap tier from the top bar', async () => {
    renderShell();
    await screen.findAllByText(/crude oil slips below \$70/i);
    fireEvent.click(screen.getByLabelText('Cap filter MID'));
    expect(screen.queryByText(/crude oil slips below \$70/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Cap filter LARGE'));
    expect(screen.getAllByText(/crude oil slips below \$70/i).length).toBeGreaterThan(0);
  });

  it('switches between bottom-nav views', async () => {
    renderShell();
    fireEvent.click(screen.getByRole('button', { name: /discover/i }));
    expect(await screen.findByText(/smaller names the headlines miss/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /directory/i }));
    expect(await screen.findByText(/every tracked stock/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /portfolio/i }));
    expect(await screen.findByText(/account aggregator/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /review/i }));
    expect(await screen.findByText(/did a flagged reaction hold or reverse/i)).toBeInTheDocument();
  });

  it('prompts sign-in on portfolio and review when logged out', async () => {
    renderShell();
    fireEvent.click(screen.getByRole('button', { name: /portfolio/i }));
    expect(
      await screen.findByText(/to see which of today's news touches your holdings/i),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /review/i }));
    expect(await screen.findByText(/to review how flagged reactions played out/i)).toBeInTheDocument();
  });

  it('opens the calendar and reopens a previous day via ?date=', async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal('fetch', fetchMock);
    renderShell();
    await screen.findByTestId('front-7');
    fireEvent.click(screen.getByTestId('calendar-button'));
    expect(await screen.findByTestId('calendar-sheet')).toBeInTheDocument();
    // Pick the 1st of the displayed month (never "today", which maps to null).
    fireEvent.click(screen.getByRole('button', { name: '1' }));
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((call) => String(call[0]));
      expect(calls.some((url) => /\/api\/feed-v2\?date=\d{4}-\d{2}-01$/.test(url))).toBe(true);
    });
    // Date bar with the back-to-today control appears.
    expect(await screen.findByText('Back to today')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Back to today'));
    expect(screen.queryByText('Back to today')).not.toBeInTheDocument();
  });

  it('refetches the feed with ?lang= when the language changes', async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal('fetch', fetchMock);
    renderShell();
    await screen.findByTestId('front-7');
    fireEvent.change(screen.getByLabelText('Language'), { target: { value: 'hi' } });
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((call) => String(call[0]));
      expect(calls.some((url) => url.includes('/api/feed-v2?lang=hi'))).toBe(true);
    });
  });

  it('closes the sheet via the scrim', async () => {
    renderShell();
    fireEvent.click(await screen.findByTestId('front-7'));
    fireEvent.click(await screen.findByLabelText('About ONGC.NS'));
    await screen.findByText('What they do');
    fireEvent.click(screen.getByTestId('scrim'));
    await waitFor(() => {
      expect(screen.getByTestId('scrim')).not.toHaveClass('on');
    });
  });
});
