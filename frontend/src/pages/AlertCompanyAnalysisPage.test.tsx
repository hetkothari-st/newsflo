import { render as rtlRender, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AlertCompanyAnalysisPage from './AlertCompanyAnalysisPage';
import * as api from '../lib/api';
import type { Alert } from '../lib/api';
import { LanguageProvider } from '../lib/language';

function render(ui: ReactElement, initialPath: string) {
  return rtlRender(
    <MemoryRouter initialEntries={[initialPath]}>
      <LanguageProvider>
        <Routes>
          <Route path="/alerts/:id/company/:companyId" element={ui} />
        </Routes>
      </LanguageProvider>
    </MemoryRouter>,
  );
}

const ALERT: Alert = {
  id: 7,
  category: 'oil_energy',
  category_label: 'Oil & Energy',
  created_at: '2026-07-17T10:00:00.000Z',
  article: { id: 1, title: 'Headline', url: 'https://example.com', image_url: null },
  event_type: 'crude_oil',
  companies: [
    {
      company_id: 1,
      ticker: 'RELIANCE.NS',
      name: 'Reliance Industries',
      index_tier: 'NIFTY50',
      direction: 'bullish',
      magnitude_low: 2,
      magnitude_high: 4,
      rationale: 'Refiner margins expand.',
      key_points: ['Refiner margins expand on crude softness.'],
      confidence_score: 84,
      time_horizon: 'Short-Term',
      basis: 'direct_mention',
      confidence: 'llm_estimate',
      market: 'IN',
      in_my_holdings: false,
      past_mentions: [],
      reasons: ['Crude softness lowers input costs.', 'Refining margins historically widen in this regime.'],
      evidence_refs: ['RULE_CRUDE_OIL_DROP', 'article:4471'],
      risks: ['Demand destruction could offset the margin gain.'],
      assumptions: ['Assumes crude stays below $70/bbl through the quarter.'],
      unknowns: [],
      alternative_hypothesis: 'If crude rebounds sharply, the margin thesis reverses.',
      confidence_contributors: ['Matched a known rulebook rule'],
      confidence_penalties: ['No historical calibration yet (2 samples, need 5)'],
      price_at_analysis: 1642.5,
      return_1m: 3.2,
      return_3m: 9.1,
      contradiction_note: null,
      impact_level: 'direct',
    },
  ],
};

describe('AlertCompanyAnalysisPage', () => {
  it('shows the company name, full reasons list, and evidence', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(ALERT);
    render(<AlertCompanyAnalysisPage />, '/alerts/7/company/1');

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.getByText('Crude softness lowers input costs.')).toBeInTheDocument();
    expect(screen.getByText('Refining margins historically widen in this regime.')).toBeInTheDocument();
  });

  it('shows risks, assumptions, and the alternative hypothesis', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(ALERT);
    render(<AlertCompanyAnalysisPage />, '/alerts/7/company/1');

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.getByText('Demand destruction could offset the margin gain.')).toBeInTheDocument();
    expect(screen.getByText('Assumes crude stays below $70/bbl through the quarter.')).toBeInTheDocument();
    expect(screen.getByText('If crude rebounds sharply, the margin thesis reverses.')).toBeInTheDocument();
  });

  it('shows confidence contributors and penalties', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(ALERT);
    render(<AlertCompanyAnalysisPage />, '/alerts/7/company/1');

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.getByText('Matched a known rulebook rule')).toBeInTheDocument();
    expect(screen.getByText('No historical calibration yet (2 samples, need 5)')).toBeInTheDocument();
  });

  it('shows the facts section with price and returns', async () => {
    // Price/returns render as adjacent leaf <span>s inside a shared div, so
    // a plain regex getByText would substring-match every ancestor's full
    // textContent too (RTL matches per-element, not just leaves) and throw
    // "multiple elements found" -- a leaf-only exact-text matcher sidesteps
    // that ambiguity entirely.
    vi.spyOn(api, 'getAlert').mockResolvedValue(ALERT);
    render(<AlertCompanyAnalysisPage />, '/alerts/7/company/1');

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(
      screen.getByText((_, el) => el?.tagName === 'SPAN' && el.textContent === '₹1642.50'),
    ).toBeInTheDocument();
    expect(
      screen.getByText((_, el) => el?.tagName === 'SPAN' && el.textContent === '+3.2% (1M)'),
    ).toBeInTheDocument();
  });

  it('shows a contradiction note with distinct treatment when present', async () => {
    const withContradiction: Alert = {
      ...ALERT,
      companies: [{ ...ALERT.companies[0], contradiction_note: 'Price down 8.3% over the past month despite bullish call.' }],
    };
    vi.spyOn(api, 'getAlert').mockResolvedValue(withContradiction);
    render(<AlertCompanyAnalysisPage />, '/alerts/7/company/1');

    await waitFor(() =>
      expect(screen.getByText('Price down 8.3% over the past month despite bullish call.')).toBeInTheDocument(),
    );
  });

  it('links to the company profile page for IN-market companies', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(ALERT);
    render(<AlertCompanyAnalysisPage />, '/alerts/7/company/1');

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    const link = screen.getByRole('link', { name: /view company details/i });
    expect(link).toHaveAttribute('href', '/company/1');
  });

  it('does not show the profile link for GLOBAL-market companies', async () => {
    const global: Alert = { ...ALERT, companies: [{ ...ALERT.companies[0], market: 'GLOBAL' }] };
    vi.spyOn(api, 'getAlert').mockResolvedValue(global);
    render(<AlertCompanyAnalysisPage />, '/alerts/7/company/1');

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.queryByRole('link', { name: /view company details/i })).not.toBeInTheDocument();
  });

  it('renders nothing crashing when the company id is not found in the alert', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(ALERT);
    render(<AlertCompanyAnalysisPage />, '/alerts/7/company/999');

    // Regex getByText would also match RTL's own render-container div here
    // (its textContent equals the single rendered <p>'s text in this
    // minimal tree) and throw "multiple elements found" -- constrain to <p>.
    await waitFor(() =>
      expect(
        screen.getByText((_, el) => el?.tagName === 'P' && /not found/i.test(el.textContent ?? '')),
      ).toBeInTheDocument(),
    );
  });
});
