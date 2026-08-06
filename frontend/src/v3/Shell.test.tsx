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
  cap_tiers: ['LARGE', 'MICRO'],
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
          // business_desc was LLM-invented and the backend now always sends
          // null; fundamentals (BSE-sourced) replaces it.
          business_desc: null,
          fundamentals: {
            classification: {
              sector: 'Energy',
              industry: 'Oil, Gas & Consumable Fuels',
              group: 'Exploration',
              sub_group: 'Oil Exploration & Production',
            },
            ratios: { pe: 9.5 },
            source: 'BSE',
            as_of: '2026-08-04',
          },
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
          // No official BSE classification for this fixture -- exercises the
          // render-nothing path (see 'shows no "What they do" section...' below).
          business_desc: null,
          fundamentals: null,
          direction: 'bullish',
          excess_move_pct: 4.7,
          intensity: { score: 83, band: 'High', components: [] },
          is_exposure_only: false,
          in_my_holdings: false,
          why: 'Cheaper crude lifts refining margins.',
          logo_url: null,
        },
        {
          ticker: 'BA',
          name: 'Boeing',
          sector: 'defense',
          cap_tier: null,
          liquidity_tier: 'HIGH',
          delivery_pct: null,
          business_desc: 'Builds commercial and military aircraft.',
          direction: 'bearish',
          excess_move_pct: -2.6,
          intensity: { score: 64, band: 'Moderate', components: [] },
          is_exposure_only: false,
          in_my_holdings: false,
          why: 'Directly named in the story.',
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
  // business_desc was LLM-invented and the backend now always sends null;
  // fundamentals (BSE-sourced) replaces it.
  business_desc: null,
  fundamentals: {
    classification: {
      sector: 'Energy',
      industry: 'Oil, Gas & Consumable Fuels',
      group: 'Petroleum Products',
      sub_group: 'Refineries & Marketing',
    },
    ratios: { pe: 6.4 },
    source: 'BSE',
    as_of: '2026-08-04',
  },
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
  why: 'Cheaper crude lifts refining margins.',
  rationale: 'A standalone refiner with full crude-cost exposure.',
  section_title: 'Winners — refiners & marketers',
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
  it('renders the card front skim layer: excess move, headline, gist, held dot', async () => {
    renderShell();
    // The headline renders on both card faces (front + condensed back head).
    expect((await screen.findAllByText(/crude oil slips below \$70/i)).length).toBe(2);
    expect(screen.getByText('▼ 2.4%')).toBeInTheDocument();
    expect(screen.getByText('excess vs sector')).toBeInTheDocument();
    // The verdict chip (Company-specific / Sector-wide) was removed -- it
    // mislabeled most stories and duplicated what the ripple shows.
    expect(screen.queryByText('Sector-wide')).not.toBeInTheDocument();
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
    // A company with no honest India cap tier (foreign listing) gets NO
    // cap chip at all -- never a "—" placeholder.
    expect(within(screen.getByTestId('srow-BA')).queryByText('—')).not.toBeInTheDocument();
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

  it('locks feed scrolling while a card is flipped to its analysis', async () => {
    renderShell();
    expect(await screen.findByTestId('feed')).not.toHaveClass('locked');
    fireEvent.click(screen.getByTestId('front-7'));
    expect(screen.getByTestId('feed')).toHaveClass('locked');
    fireEvent.click(await screen.findByLabelText('Back to headline'));
    expect(screen.getByTestId('feed')).not.toHaveClass('locked');
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
    // Sourced classification/ratio/date replace the old business_desc
    // paragraph in the deep-dive's own "What they do" section too.
    expect(sheet.getByText(/Refineries & Marketing/)).toBeInTheDocument();
    // Deep dive speaks the same plain language as the glance now -- "6.4×"
    // under "Price vs yearly profit", not a bare "P/E 6.40" code.
    expect(sheet.getByText('Price vs yearly profit')).toBeInTheDocument();
    expect(sheet.getByText('6.4×')).toBeInTheDocument();
    expect(sheet.getByText(/2026-08-04/)).toBeInTheDocument();
    expect(sheet.getByText(/how this score is built/i)).toBeInTheDocument();
    expect(sheet.getByText('Materiality')).toBeInTheDocument();
    expect(sheet.getByText(/only 38% of volume went to delivery/i)).toBeInTheDocument();
    expect(sheet.getByText(/small size and thin trading amplify moves/i)).toBeInTheDocument();
    // Per-story reasoning block below "What they do": section membership +
    // 1-2 points on why this company is affected by this news.
    expect(sheet.getByText(/why it's under "winners — refiners & marketers"/i)).toBeInTheDocument();
    const bullets = within(sheet.getByTestId('why-list')).getAllByRole('listitem');
    expect(bullets.map((b) => b.textContent)).toEqual([
      'Cheaper crude lifts refining margins.',
      'A standalone refiner with full crude-cost exposure.',
    ]);
    expect(sheet.getByText(/not whether it's a good investment/i)).toBeInTheDocument();
  });

  it('opens the (i) glance popup without opening the deep dive', async () => {
    renderShell();
    fireEvent.click(await screen.findByTestId('front-7'));
    fireEvent.click(await screen.findByLabelText('About ONGC.NS'));
    expect(await screen.findByText('What they do')).toBeInTheDocument();
    // The sourced classification and ratio replace the old business_desc
    // paragraph -- see docs/superpowers/specs/2026-08-04-sourced-company-
    // fundamentals-design.md. The date is load-bearing (spec 5.1), not
    // decoration: PE is price-derived and this data refreshes monthly.
    expect(screen.getByText(/Oil Exploration & Production/)).toBeInTheDocument();
    // Glance speaks plain language ("Price vs yearly profit 9.5×"), not
    // ratio codes -- laypeople don't know what P/E means.
    expect(screen.getByText('Price vs yearly profit')).toBeInTheDocument();
    expect(screen.getByText('9.5×')).toBeInTheDocument();
    expect(screen.getByText(/2026-08-04/)).toBeInTheDocument();
    expect(screen.getByText(/glance view/i)).toBeInTheDocument();
    // Deep-dive-only content must NOT be present -- (i) = glance and stay.
    expect(screen.queryByText(/how this score is built/i)).not.toBeInTheDocument();
  });

  it('shows no "What they do" section at all for a company with no BSE classification', async () => {
    renderShell();
    fireEvent.click(await screen.findByTestId('front-7'));
    fireEvent.click(await screen.findByLabelText('About CHENNPETRO.NS'));
    expect(await screen.findByText(/glance view/i)).toBeInTheDocument();
    expect(screen.queryByText('What they do')).not.toBeInTheDocument();
    expect(screen.queryByTestId('fundamentals')).not.toBeInTheDocument();
  });

  it('filters the feed by cap tier from the top bar', async () => {
    renderShell();
    await screen.findAllByText(/crude oil slips below \$70/i);
    fireEvent.click(screen.getByLabelText('Cap filter MID'));
    expect(screen.queryByText(/crude oil slips below \$70/i)).not.toBeInTheDocument();
    // A filter that matches nothing must say so -- never a silent blank feed.
    expect(screen.getByText(/no stories in this cap tier/i)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Cap filter LARGE'));
    expect(screen.getAllByText(/crude oil slips below \$70/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/no stories in this cap tier/i)).not.toBeInTheDocument();
  });

  it('matches a story when ANY tagged company sits in the chosen tier, not only the peak', async () => {
    // Peak is LARGE (ONGC) but the story also tags a MICRO refiner
    // (cap_tiers: ['LARGE', 'MICRO']) -- the µ filter must keep it visible.
    renderShell();
    await screen.findAllByText(/crude oil slips below \$70/i);
    fireEvent.click(screen.getByLabelText('Cap filter MICRO'));
    expect(screen.getAllByText(/crude oil slips below \$70/i).length).toBeGreaterThan(0);
  });

  it('filters the card-back company rows by the chosen cap tier', async () => {
    // The back lists ONGC (LARGE) and CHENNPETRO (MICRO). Under the µ
    // filter only the MICRO row may remain -- "show me small caps" means
    // the company rows too, not just which stories survive.
    renderShell();
    fireEvent.click(await screen.findByTestId('front-7'));
    await screen.findByTestId('srow-ONGC.NS');
    fireEvent.click(screen.getByLabelText('Cap filter MICRO'));
    expect(screen.queryByTestId('srow-ONGC.NS')).not.toBeInTheDocument();
    expect(screen.getByTestId('srow-CHENNPETRO.NS')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Cap filter ALL'));
    expect(screen.getByTestId('srow-ONGC.NS')).toBeInTheDocument();
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
