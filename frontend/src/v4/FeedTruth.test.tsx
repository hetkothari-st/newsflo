/* Task 17: one semantic source per concept, verified. Every price-sign
   fallback the v4 UI used to fall back on (reaction color/arrow from a
   raw excess sign, winners/losers buckets from the legacy
   AlertCompany.direction alone) is gone -- these tests pin the server's
   dead-zone-classified reaction and the gate's economic_effect as the
   ONLY sources, with the legacy fields used strictly as a fallback for
   pre-gate rows that never carry the new ones at all. */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../lib/auth';
import FeedV4, { reactionArrow, reactionClass } from './FeedV4';
import DeepDiveV4 from './DeepDiveV4';
import { CSplit } from './charts/chartComponents';
import * as api from '../v3/api';
import type { AlertDetail, FeedAlert, LayerRow, RippleLayer, StockDeepDive } from '../v3/api';

function makeAlert(overrides: Partial<FeedAlert> = {}): FeedAlert {
  return {
    id: 1,
    category: 'oil_gas',
    category_label: null,
    created_at: '2026-08-13T10:00:00Z',
    summary_short: 'Oil supply shock lifts refiners',
    summary_long: null,
    article: {
      id: 1,
      image_url: null,
      title: 'Oil surges on supply shock',
      url: 'https://example.com/a',
      source: 'Economic Times',
      published_at: null,
    },
    excess_move_pct: 0.1,
    direction: 'flat',
    market_reaction: {
      status: 'ok',
      direction: 'flat',
      bar_complete: 1,
      raw_move_pct: 0.1,
      excess_move_pct: 0.1,
      benchmark_ticker: '^CNXENERGY',
      benchmark_is_fallback: false,
      data_quality: 'ok',
      session_state: 'closed',
      reaction_significance: 'noise',
    },
    raw_move_pct: 0.1,
    sector_move_pct: 0.05,
    volume_multiple: 1.2,
    benchmark_ticker: '^CNXENERGY',
    is_fallback_benchmark: false,
    peak_ticker: 'RELIANCE.NS',
    peak_company_name: 'Reliance Industries',
    peak_cap_tier: 'LARGE',
    cap_tiers: ['LARGE'],
    verdict: 'COMPANY_SPECIFIC',
    intensity: { score: 40, band: 'Low', components: [] },
    breadth_score: 10,
    in_my_holdings: false,
    ...overrides,
  };
}

function makeRow(overrides: Partial<LayerRow> = {}): LayerRow {
  return {
    ticker: 'BPCL.NS',
    name: 'Bharat Petroleum',
    sector: 'oil_gas',
    cap_tier: 'LARGE',
    liquidity_tier: 'HIGH',
    delivery_pct: null,
    business_desc: null,
    business_desc_source_url: null,
    fundamentals: null,
    direction: 'bullish',
    excess_move_pct: 2.0,
    intensity: null,
    is_exposure_only: false,
    in_my_holdings: false,
    why: null,
    logo_url: null,
    ...overrides,
  };
}

function makeLayer(rows: LayerRow[], overrides: Partial<RippleLayer> = {}): RippleLayer {
  return { title: 'Directly hit', relationship: 'DIRECT', icon: 'win', note: null, rows, ...overrides };
}

function makeDetail(alert: FeedAlert, layers: RippleLayer[]): AlertDetail {
  return { ...alert, layers, timeline: [], edges: [] };
}

function renderFeed() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <FeedV4
          date="2026-08-13"
          onEdition={() => {}}
          onOpenDeepDive={() => {}}
          onOpenInfo={() => {}}
          onBandOpenChange={() => {}}
        />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('reactionClass / reactionArrow', () => {
  it('renders flat with no reaction, never sign-derived from the raw excess', () => {
    expect(reactionClass(null)).toBe('flat');
    expect(reactionClass(undefined)).toBe('flat');
    expect(reactionArrow(null)).toBe('');
    expect(reactionArrow(undefined)).toBe('');
  });

  it('still derives up/down from a real reaction_direction', () => {
    expect(reactionClass({ direction: 'positive' })).toBe('up');
    expect(reactionClass({ direction: 'negative' })).toBe('down');
    expect(reactionArrow({ direction: 'positive' })).toBe('▲');
    expect(reactionArrow({ direction: 'negative' })).toBe('▼');
  });
});

describe('FeedV4 hero', () => {
  it('renders no arrow and a neutral class when the reaction is flat', async () => {
    vi.spyOn(api, 'getFeedAlerts').mockResolvedValue([makeAlert()]);
    const { container } = renderFeed();
    await waitFor(() => screen.getByText('Oil surges on supply shock'));
    const lmove = container.querySelector('.lmove');
    expect(lmove).not.toBeNull();
    expect(lmove!.className.split(' ')).toContain('flat');
    expect(lmove!.className.split(' ')).not.toContain('up');
    expect(lmove!.className.split(' ')).not.toContain('down');
    expect(lmove!.textContent).not.toMatch(/[▲▼]/);
  });
});

describe('FeedV4 company row', () => {
  it('shows the fundamental label and divergence line when effect and reaction disagree', async () => {
    const alert = makeAlert({ id: 2 });
    const row = makeRow({
      ticker: 'IOC.NS',
      economic_effect: 'negative',
      materiality_grade: 'HIGH',
      reaction_direction: 'positive',
      divergence: 'Stock is currently moving up despite a negative fundamental exposure thesis.',
      excess_move_pct: 1.8,
    });
    const detail = makeDetail(alert, [makeLayer([row])]);
    vi.spyOn(api, 'getFeedAlerts').mockResolvedValue([alert]);
    vi.spyOn(api, 'getAlertDetail').mockResolvedValue(detail);
    renderFeed();
    await waitFor(() => screen.getByText('Oil surges on supply shock'));
    fireEvent.click(screen.getByText("See who's affected →"));
    await waitFor(() => screen.getByTestId('v4row-IOC.NS'));
    expect(screen.getByText('NEGATIVE · HIGH')).toBeInTheDocument();
    expect(
      screen.getByText('Stock is currently moving up despite a negative fundamental exposure thesis.'),
    ).toBeInTheDocument();
  });
});

describe('CSplit bucketing', () => {
  it('buckets winners/losers by economic_effect, using legacy direction only as a fallback', () => {
    const alert = makeAlert({ id: 3 });
    const rowA = makeRow({
      ticker: 'A.NS', direction: 'bullish', economic_effect: 'negative', excess_move_pct: 2.0,
    });
    const rowB = makeRow({
      ticker: 'B.NS', direction: 'bullish', economic_effect: undefined, excess_move_pct: 1.5,
    });
    const rowC = makeRow({
      ticker: 'C.NS', direction: 'bearish', economic_effect: 'mixed', excess_move_pct: -0.5,
    });
    const detail = makeDetail(alert, [makeLayer([rowA, rowB, rowC])]);
    const { container } = render(<CSplit detail={detail} />);
    // A.NS: direction says "bullish" but the gate's economic_effect says
    // "negative" -- the fundamental verdict wins, it lands in losers.
    expect(container.querySelector('.csplit-col.down [data-ticker="A.NS"]')).not.toBeNull();
    expect(container.querySelector('.csplit-col.up [data-ticker="A.NS"]')).toBeNull();
    // Node color must follow the SAME effect key as bucket placement --
    // A.NS has a +2.0% excess move but its economic_effect is negative,
    // so the node itself must render "down"/red, never green off the
    // raw positive sign (the bug this fix addresses).
    const nodeA = container.querySelector('[data-ticker="A.NS"]');
    expect(nodeA).not.toBeNull();
    expect(nodeA!.className.split(' ')).toContain('down');
    expect(nodeA!.className.split(' ')).not.toContain('up');
    expect(container.querySelector('[data-ticker="A.NS"] .cnode-mv')?.className.split(' ')).toContain('down');
    // B.NS: no economic_effect at all (legacy row) -- direction fallback
    // still applies, it lands in winners.
    expect(container.querySelector('.csplit-col.up [data-ticker="B.NS"]')).not.toBeNull();
    // C.NS: economic_effect "mixed" -- neither a winner nor a loser, but
    // never dropped from the chart.
    expect(container.querySelector('.csplit-col.down [data-ticker="C.NS"]')).toBeNull();
    expect(container.querySelector('.csplit-col.up [data-ticker="C.NS"]')).toBeNull();
    expect(screen.getByText('Positive impact · 1')).toBeInTheDocument();
    expect(screen.getByText('Negative impact · 1')).toBeInTheDocument();
    expect(screen.getByText('No net effect / exposure only · 1')).toBeInTheDocument();
  });
});

describe('DeepDiveV4 excess chip', () => {
  it('never renders a 0.0 excess move as a green gain', async () => {
    const data: StockDeepDive = {
      ticker: 'IOC.NS',
      name: 'Indian Oil',
      sector: 'oil_gas',
      cap_tier: 'LARGE',
      business_desc: null,
      business_desc_source_url: null,
      fundamentals: null,
      logo_url: null,
      market_cap: null,
      pe: null,
      in_my_holdings: false,
      excess_move_pct: 0.0,
      raw_move_pct: 0.1,
      sector_move_pct: 0.1,
      volume_multiple: null,
      liquidity_tier: null,
      delivery_pct: null,
      intensity: null,
      is_exposure_only: false,
      why: null,
      rationale: null,
      section_title: null,
      peers: [],
      volatility_range: null,
    };
    vi.spyOn(api, 'getStockDeepDive').mockResolvedValue(data);
    render(
      <AuthProvider>
        <DeepDiveV4 ticker="IOC.NS" onOpenPeer={() => {}} onOpenInfo={() => {}} onClose={() => {}} />
      </AuthProvider>,
    );
    const chip = await screen.findByText('0.0%');
    expect(chip.className.split(' ')).toContain('flat');
    expect(chip.className.split(' ')).not.toContain('up');
  });
});
