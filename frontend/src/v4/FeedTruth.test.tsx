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
import { CLevels, CSplit } from './charts/chartComponents';
import { availableCharts, isLevelOne } from './charts/chartsData';
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

/* --- final-review findings I5 / I9 / I10 ------------------------------- */

describe('honest-unavailable measurement (finding I5)', () => {
  it('renders the ripple band without throwing and shows dashes for null moves', async () => {
    // Exactly what backend feed_v2._unavailable_measurement serves when
    // the price feed failed (spec §49): the fundamental analysis stays
    // visible and EVERY market field is null. raw_move_pct /
    // sector_move_pct were typed non-nullable, so fmtPct called .toFixed
    // on null and the whole feed crashed on the payload the backend built
    // to be honest.
    const alert = makeAlert({
      id: 42,
      excess_move_pct: null,
      direction: null,
      raw_move_pct: null,
      sector_move_pct: null,
      volume_multiple: null,
      market_reaction: {
        status: 'unavailable',
        direction: 'unknown',
        bar_complete: null,
        raw_move_pct: null,
        excess_move_pct: null,
        benchmark_ticker: null,
        benchmark_is_fallback: false,
        data_quality: null,
        session_state: null,
        reaction_significance: 'unknown',
      },
    });
    const detail = makeDetail(alert, [makeLayer([makeRow({ excess_move_pct: null })])]);
    vi.spyOn(api, 'getFeedAlerts').mockResolvedValue([alert]);
    vi.spyOn(api, 'getAlertDetail').mockResolvedValue(detail);

    renderFeed();
    await waitFor(() => screen.getByText('Oil surges on supply shock'));
    fireEvent.click(screen.getByText("See who's affected →"));
    await waitFor(() => screen.getByTestId('v4row-BPCL.NS'));

    // Raw / Sector / Volume all render an em dash, never "0.0%".
    const sumline = document.querySelector('.sumline');
    expect(sumline).not.toBeNull();
    expect(sumline!.textContent).toContain('—');
    expect(sumline!.textContent).not.toContain('0.0%');
  });
});

describe('chart availability vs bucketing (finding I9)', () => {
  it('does not offer the split tile when no row has a measured move', () => {
    const alert = makeAlert({ id: 5 });
    // Exposure-only rows: a real economic_effect on each side, but no
    // measured move anywhere. Availability used to say "show it" (it
    // ignored excess_move_pct) while the bucketing -- which requires a
    // measured move -- put every row in neutral, rendering
    // "Positive impact · 0 / Negative impact · 0".
    const detail = makeDetail(alert, [
      makeLayer([
        makeRow({ ticker: 'X.NS', economic_effect: 'positive', excess_move_pct: null }),
        makeRow({ ticker: 'Y.NS', economic_effect: 'negative', excess_move_pct: null }),
      ]),
    ]);
    expect(availableCharts(detail).map((chart) => chart.kind)).not.toContain('split');
  });

  it('still offers the split tile once both sides carry a measured move', () => {
    const alert = makeAlert({ id: 6 });
    const detail = makeDetail(alert, [
      makeLayer([
        makeRow({ ticker: 'X.NS', economic_effect: 'positive', excess_move_pct: 2.0 }),
        makeRow({ ticker: 'Y.NS', economic_effect: 'negative', excess_move_pct: -1.5 }),
      ]),
    ]);
    expect(availableCharts(detail).map((chart) => chart.kind)).toContain('split');
  });

  it('availability and bucketing agree: an offered split tile is never empty', () => {
    const alert = makeAlert({ id: 7 });
    const detail = makeDetail(alert, [
      makeLayer([
        makeRow({ ticker: 'X.NS', economic_effect: 'positive', excess_move_pct: 2.0 }),
        makeRow({ ticker: 'Y.NS', economic_effect: 'negative', excess_move_pct: -1.5 }),
      ]),
    ]);
    render(<CSplit detail={detail} />);
    expect(screen.getByText('Positive impact · 1')).toBeInTheDocument();
    expect(screen.getByText('Negative impact · 1')).toBeInTheDocument();
  });
});

describe('deck level detection on gated alerts (finding I10)', () => {
  it('treats a MECH: layer as level 1, like DIRECT', () => {
    // A gated alert's sections emit "MECH:{label}" / "SECONDARY" -- never
    // the legacy "DIRECT" -- so the literal compare put every company on
    // a gated story into level 2+ and left the "Direct impact" band empty.
    const alert = makeAlert({ id: 8 });
    const detail = makeDetail(alert, [
      makeLayer([makeRow({ ticker: 'M.NS' })], {
        title: 'Crude-linked input costs',
        relationship: 'MECH:crude_input_cost',
      }),
    ]);
    const { container } = render(<CLevels detail={detail} />);
    const labels = [...container.querySelectorAll('.clevel-label')].map((el) => el.textContent);
    expect(labels[0]).toContain('Level 1');
    expect(labels[0]).toContain('Direct impact');
    expect(container.querySelector('[data-ticker="M.NS"]')).not.toBeNull();
  });

  it('keeps SECONDARY on the indirect level, not the direct one', () => {
    const alert = makeAlert({ id: 9 });
    const detail = makeDetail(alert, [
      makeLayer([makeRow({ ticker: 'M.NS' })], {
        title: 'Crude-linked input costs',
        relationship: 'MECH:crude_input_cost',
      }),
      makeLayer([makeRow({ ticker: 'S.NS' })], {
        title: 'Wider ecosystem',
        relationship: 'SECONDARY',
      }),
    ]);
    expect(isLevelOne({ relationship: 'MECH:crude_input_cost' })).toBe(true);
    expect(isLevelOne({ relationship: 'SECONDARY' })).toBe(false);
    expect(isLevelOne({ relationship: 'DIRECT' })).toBe(true);

    const { container } = render(<CLevels detail={detail} />);
    const bands = [...container.querySelectorAll('.clevel')];
    expect(bands).toHaveLength(2);
    expect(bands[0].querySelector('[data-ticker="M.NS"]')).not.toBeNull();
    expect(bands[1].querySelector('[data-ticker="S.NS"]')).not.toBeNull();
  });
});

/* --- Task 9: five-dimension display, taxonomy/macro sections, band-only
   confidence (final-blueprint §15/§28/§29, ruling R4). Backend Task 6
   ships causal_directness/publication_tier/confidence_band/event_scope
   later -- every field here is optional and these tests mock the payload
   directly, nothing depends on a live backend. --------------------------- */

describe('directness + tier row line (spec §28, Task 9)', () => {
  it('renders "DIRECT EXPOSURE · PRIMARY" from causal_directness + publication_tier', async () => {
    const alert = makeAlert({ id: 20 });
    const row = makeRow({ ticker: 'ONGC.NS', causal_directness: 'DIRECT', publication_tier: 'primary' });
    const detail = makeDetail(alert, [makeLayer([row])]);
    vi.spyOn(api, 'getFeedAlerts').mockResolvedValue([alert]);
    vi.spyOn(api, 'getAlertDetail').mockResolvedValue(detail);
    renderFeed();
    await waitFor(() => screen.getByText('Oil surges on supply shock'));
    fireEvent.click(screen.getByText("See who's affected →"));
    await waitFor(() => screen.getByTestId('v4row-ONGC.NS'));
    expect(screen.getByText('DIRECT EXPOSURE · PRIMARY')).toBeInTheDocument();
  });

  it('maps secondary_ripple to RIPPLE and macro_context to MACRO, and REMOTE drops the EXPOSURE suffix', async () => {
    const alert = makeAlert({ id: 21 });
    const rowRipple = makeRow({ ticker: 'IOC.NS', causal_directness: 'INDIRECT', publication_tier: 'secondary_ripple' });
    const rowMacro = makeRow({ ticker: 'INR.NS', causal_directness: 'REMOTE', publication_tier: 'macro_context' });
    const detail = makeDetail(alert, [makeLayer([rowRipple, rowMacro])]);
    vi.spyOn(api, 'getFeedAlerts').mockResolvedValue([alert]);
    vi.spyOn(api, 'getAlertDetail').mockResolvedValue(detail);
    renderFeed();
    await waitFor(() => screen.getByText('Oil surges on supply shock'));
    fireEvent.click(screen.getByText("See who's affected →"));
    await waitFor(() => screen.getByTestId('v4row-IOC.NS'));
    expect(screen.getByText('INDIRECT EXPOSURE · RIPPLE')).toBeInTheDocument();
    expect(screen.getByText('REMOTE · MACRO')).toBeInTheDocument();
  });

  it('maps the dead legacy tier spellings (secondary_deep_dive / secondary) to RIPPLE too', async () => {
    const alert = makeAlert({ id: 28 });
    const rowA = makeRow({ ticker: 'LEG1.NS', causal_directness: 'INDIRECT', publication_tier: 'secondary_deep_dive' });
    const rowB = makeRow({ ticker: 'LEG2.NS', causal_directness: 'DIRECT', publication_tier: 'secondary' });
    const detail = makeDetail(alert, [makeLayer([rowA, rowB])]);
    vi.spyOn(api, 'getFeedAlerts').mockResolvedValue([alert]);
    vi.spyOn(api, 'getAlertDetail').mockResolvedValue(detail);
    renderFeed();
    await waitFor(() => screen.getByText('Oil surges on supply shock'));
    fireEvent.click(screen.getByText("See who's affected →"));
    await waitFor(() => screen.getByTestId('v4row-LEG1.NS'));
    expect(screen.getByText('INDIRECT EXPOSURE · RIPPLE')).toBeInTheDocument();
    expect(screen.getByText('DIRECT EXPOSURE · RIPPLE')).toBeInTheDocument();
  });

  it('renders nothing when causal_directness/publication_tier are absent -- legacy rows', async () => {
    const alert = makeAlert({ id: 22 });
    const row = makeRow({ ticker: 'LEGACY.NS' }); // no directness/tier fields at all
    const detail = makeDetail(alert, [makeLayer([row])]);
    vi.spyOn(api, 'getFeedAlerts').mockResolvedValue([alert]);
    vi.spyOn(api, 'getAlertDetail').mockResolvedValue(detail);
    renderFeed();
    await waitFor(() => screen.getByText('Oil surges on supply shock'));
    fireEvent.click(screen.getByText("See who's affected →"));
    const rowEl = await waitFor(() => screen.getByTestId('v4row-LEGACY.NS'));
    expect(rowEl.querySelector('.dtl4')).toBeNull();
  });
});

describe('macro-context layer styling (spec §29, Task 9)', () => {
  it('gets the macro4 class only on the layer whose relationship starts with MACRO:', async () => {
    const alert = makeAlert({ id: 23 });
    const detail = makeDetail(alert, [
      makeLayer([makeRow({ ticker: 'M1.NS' })], {
        title: 'Macro context — imported inflation',
        relationship: 'MACRO:imported_inflation',
      }),
      makeLayer([makeRow({ ticker: 'M2.NS' })], { title: 'Directly hit', relationship: 'DIRECT' }),
    ]);
    vi.spyOn(api, 'getFeedAlerts').mockResolvedValue([alert]);
    vi.spyOn(api, 'getAlertDetail').mockResolvedValue(detail);
    const { container } = renderFeed();
    await waitFor(() => screen.getByText('Oil surges on supply shock'));
    fireEvent.click(screen.getByText("See who's affected →"));
    await waitFor(() => screen.getByTestId('v4row-M1.NS'));
    const layers = [...container.querySelectorAll('.layer4')];
    expect(layers).toHaveLength(2);
    expect(layers[0].className.split(' ')).toContain('macro4');
    expect(layers[1].className.split(' ')).not.toContain('macro4');
  });
});

describe('meta badge switches on event_scope (spec §15, Task 9)', () => {
  it('shows "Multi-sector impact" when event_scope is multi_sector', async () => {
    const alert = makeAlert({ id: 24, exposure: 'indirect_only', event_scope: 'multi_sector' });
    vi.spyOn(api, 'getFeedAlerts').mockResolvedValue([alert]);
    renderFeed();
    await waitFor(() => screen.getByText('Oil surges on supply shock'));
    expect(screen.getByText('Multi-sector impact')).toBeInTheDocument();
    expect(screen.queryByText('Indirect exposure')).not.toBeInTheDocument();
  });

  it('falls back to "Indirect exposure" when event_scope is absent', async () => {
    const alert = makeAlert({ id: 25, exposure: 'indirect_only' });
    vi.spyOn(api, 'getFeedAlerts').mockResolvedValue([alert]);
    renderFeed();
    await waitFor(() => screen.getByText('Oil surges on supply shock'));
    expect(screen.getByText('Indirect exposure')).toBeInTheDocument();
  });
});

describe('confidence band chip -- band only, never numeric (ruling R4, Task 9)', () => {
  it('renders the confidence_band chip verbatim, with no numeric confidence anywhere on the row', async () => {
    const alert = makeAlert({ id: 26 });
    const row = makeRow({ ticker: 'CB.NS', confidence_band: 'HIGH' });
    const detail = makeDetail(alert, [makeLayer([row])]);
    vi.spyOn(api, 'getFeedAlerts').mockResolvedValue([alert]);
    vi.spyOn(api, 'getAlertDetail').mockResolvedValue(detail);
    renderFeed();
    await waitFor(() => screen.getByText('Oil surges on supply shock'));
    fireEvent.click(screen.getByText("See who's affected →"));
    const rowEl = await waitFor(() => screen.getByTestId('v4row-CB.NS'));
    const chip = rowEl.querySelector('.cband4');
    expect(chip).not.toBeNull();
    expect(chip!.textContent).toBe('HIGH');
    // Band-only display: no "confidence: <number>" text anywhere on the
    // row. LayerRow carries no confidence_score field at all, so this
    // also holds structurally, not just by this render's choices.
    expect(rowEl.textContent).not.toMatch(/confidence[^a-z]*\d/i);
  });

  it('renders no confidence chip when confidence_band is absent', async () => {
    const alert = makeAlert({ id: 27 });
    const row = makeRow({ ticker: 'NB.NS' });
    const detail = makeDetail(alert, [makeLayer([row])]);
    vi.spyOn(api, 'getFeedAlerts').mockResolvedValue([alert]);
    vi.spyOn(api, 'getAlertDetail').mockResolvedValue(detail);
    renderFeed();
    await waitFor(() => screen.getByText('Oil surges on supply shock'));
    fireEvent.click(screen.getByText("See who's affected →"));
    const rowEl = await waitFor(() => screen.getByTestId('v4row-NB.NS'));
    expect(rowEl.querySelector('.cband4')).toBeNull();
  });
});
