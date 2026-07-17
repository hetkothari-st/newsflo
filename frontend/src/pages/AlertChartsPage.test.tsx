import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AlertChartsPage from './AlertChartsPage';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider } from '../lib/language';
import * as api from '../lib/api';
import type { Alert } from '../lib/api';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

function alert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 1,
    category: 'oil_energy',
    category_label: 'Oil & Energy',
    created_at: '2026-07-14T00:00:00Z',
    article: { id: 1, title: 'Crude prices ease on supply news', url: 'https://example.com', image_url: null },
    companies: [
      {
        company_id: 1, ticker: 'RIL', name: 'Reliance Industries', index_tier: 'NIFTY50', sector: 'oil_gas',
        direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'Refiner margins widen.',
        key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
        in_my_holdings: false, past_mentions: [],
      },
    ],
    ...overrides,
  };
}

const directCompany = {
  company_id: 1, ticker: 'RIL', name: 'Reliance Industries', index_tier: 'NIFTY50', sector: 'oil_gas',
  direction: 'bullish' as const, magnitude_low: 2, magnitude_high: 4, rationale: 'Refiner margins widen.',
  key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN' as const,
  in_my_holdings: false, past_mentions: [],
};

const inferredCompany = {
  company_id: 2, ticker: 'ONGC', name: 'Oil and Natural Gas Corporation', index_tier: 'NIFTY50', sector: 'oil_gas',
  direction: 'bearish' as const, magnitude_low: 1, magnitude_high: 2, rationale: 'Sector-wide pressure on crude producers.',
  key_points: [], confidence_score: 30, time_horizon: 'Short-Term', basis: 'sector_inference', confidence: 'llm_estimate', market: 'IN' as const,
  in_my_holdings: false, past_mentions: [],
};

const indirectCompany = {
  company_id: 3, ticker: 'TSM', name: 'TSMC', index_tier: 'NIFTY50', sector: 'it',
  direction: 'bearish' as const, magnitude_low: 1, magnitude_high: 2, rationale: 'Fabs Reliance-adjacent chips.',
  key_points: [], confidence_score: 20, time_horizon: 'Medium-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN' as const,
  in_my_holdings: false, past_mentions: [], impact_level: 'indirect_l1', parent_company_id: 1,
};

function renderPage(id = '1') {
  return render(
    <LanguageProvider>
      <AuthProvider>
        <MemoryRouter initialEntries={[`/alerts/${id}/charts`]}>
          <Routes>
            <Route path="/alerts/:id/charts" element={<AlertChartsPage />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </LanguageProvider>,
  );
}

describe('AlertChartsPage', () => {
  it('fetches the alert by route id and shows the article title', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');
    await waitFor(() => expect(screen.getByText('Crude prices ease on supply news')).toBeInTheDocument());
  });

  it('shows the pager labels for all six chart types', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');
    await waitFor(() => expect(screen.getByText('8 · Sector')).toBeInTheDocument());
    expect(screen.getByText('Tier')).toBeInTheDocument();
    expect(screen.getByText('Impact')).toBeInTheDocument();
    expect(screen.getByText('6 · Split')).toBeInTheDocument();
    expect(screen.getByText('5 · Confidence')).toBeInTheDocument();
    expect(screen.getByText('7 · Timeline')).toBeInTheDocument();
  });

  it('advances to the next chart type when the pager control is clicked', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');
    // Normal view now shows the company both in the new "Directly Affected
    // Sectors" grid and in the default Impact Tree chart tab below it, so it
    // legitimately appears twice (same pattern as the ChartCardShell legend collision).
    await waitFor(() => expect(screen.getAllByText('RIL')).toHaveLength(2));
    fireEvent.click(screen.getByText('Tier'));
    // Tier view renders the same company under a tier-row label instead of a sector tile.
    await waitFor(() => expect(screen.getByText('Nifty 50')).toBeInTheDocument());
  });

  it('shows an error state when the fetch fails', async () => {
    vi.spyOn(api, 'getAlert').mockRejectedValue(new Error('Alert not found'));
    renderPage('999');
    await waitFor(() => expect(screen.getByText('Alert not found')).toBeInTheDocument());
  });

  it('Normal view shows direct and sector-inferred companies (both impact_level=direct); Drilldown adds indirect ones too', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert({ companies: [directCompany, inferredCompany, indirectCompany] }));
    renderPage('1');
    // Normal: both direct_mention (RIL) and sector_inference (ONGC) count as
    // impact_level="direct" -- only genuinely indirect companies are hidden.
    // Each appears twice: once in the new "Directly Affected Sectors" grid,
    // once in the default Impact Tree chart tab below it (both are still shown in Normal).
    await waitFor(() => expect(screen.getAllByText('RIL')).toHaveLength(2));
    expect(screen.getAllByText('ONGC')).toHaveLength(2);
    expect(screen.queryByText('TSM')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('Drilldown'));
    // Drilldown pins its own LevelTree overview above the chart-tab carousel
    // (Task 9), and the carousel's default tab (index 0) is also the Impact
    // Tree, so every company below now renders twice.
    await waitFor(() => expect(screen.getAllByText('TSM')).toHaveLength(2));
    expect(screen.getAllByText('RIL')).toHaveLength(2);
    expect(screen.getAllByText('ONGC')).toHaveLength(2);
  });

  it('shows the no-direct-companies message in Normal view when every company is indirect', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert({ companies: [indirectCompany] }));
    renderPage('1');
    await waitFor(() =>
      expect(
        screen.getByText('No directly-confirmed companies for this alert — try Drilldown for the wider sector picture.'),
      ).toBeInTheDocument(),
    );
  });

  it('shows the Levels tab and groups an indirect company under its parent', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert({ companies: [directCompany, indirectCompany] }));
    renderPage('1');
    await waitFor(() => expect(screen.getByText('1 · Impact Tree')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Drilldown'));
    fireEvent.click(screen.getByText('1 · Impact Tree'));
    // LevelTree's ChartCardShell legend statically lists all three level
    // labels, so an active level's label appears twice (section header +
    // legend entry) rather than once -- and Drilldown pins its own LevelTree
    // overview above the chart-tab carousel (Task 9's documented duplication),
    // so with the Levels tab also selected below, everything doubles again to 4.
    await waitFor(() => expect(screen.getAllByText('Direct Impact')).toHaveLength(4));
    expect(screen.getAllByText('Indirect Impact — Level 1')).toHaveLength(4);
    expect(screen.getAllByText(/via Reliance Industries/i)).toHaveLength(2);
  });
});

describe('AlertChartsPage Normal View', () => {
  it('renders a Directly Affected Sectors section and an Impact Summary banner from real alert data', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(
      alert({
        event_type: 'repo_rate_change',
        companies: [
          {
            company_id: 1, ticker: 'HDFCBANK', name: 'HDFC Bank', index_tier: 'NIFTY50', sector: 'banking',
            direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'lower funding cost',
            key_points: [], confidence_score: 90, time_horizon: 'Short-Term', basis: 'direct_mention',
            confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [], impact_level: 'direct',
          },
        ],
      }),
    );

    renderPage();

    await waitFor(() => expect(screen.getByText('Directly Affected Sectors')).toBeInTheDocument());
    expect(screen.getByText('Impact Summary')).toBeInTheDocument();
    // Appears twice: once in the new Directly Affected Sectors grid, once in
    // the default Impact Tree chart tab still rendered below it.
    expect(screen.getAllByText('HDFCBANK')).toHaveLength(2);
  });
});

describe('AlertChartsPage Drilldown View', () => {
  it('shows Expand All / Collapse All controls and a Full Impact Summary banner', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue({
      id: 1,
      category: 'banking',
      category_label: 'Banking',
      created_at: '2026-07-17T00:00:00Z',
      article: { id: 1, title: 'RBI cuts repo rate', url: 'https://example.com', image_url: null },
      event_type: 'repo_rate_change',
      companies: [
        {
          company_id: 1, ticker: 'HDFCBANK', name: 'HDFC Bank', index_tier: 'NIFTY50', sector: 'banking',
          direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'lower funding cost',
          key_points: [], confidence_score: 90, time_horizon: 'Short-Term', basis: 'direct_mention',
          confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [], impact_level: 'direct',
        },
      ],
    } as api.Alert);

    renderPage();
    await waitFor(() => expect(screen.getByText('RBI cuts repo rate')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /drilldown/i }));

    expect(screen.getByRole('button', { name: /expand all/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /collapse all/i })).toBeInTheDocument();
    expect(screen.getByText('Full Impact Summary')).toBeInTheDocument();
  });
});
