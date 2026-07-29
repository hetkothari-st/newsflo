import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import AlertCompanies from './AlertCompanies';
import type { Alert } from '../lib/api';
import { LanguageProvider } from '../lib/language';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

function render(ui: ReactElement) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>{ui}</LanguageProvider>
    </MemoryRouter>,
  );
}

const alert: Alert = {
  id: 1,
  category: 'oil_energy',
  category_label: 'oil_energy',
  created_at: '2026-07-09T10:00:00+00:00',
  article: { id: 1, title: 'US strikes Iran oil export sites', url: 'https://example.com/a', image_url: null },
  companies: [
    {
      company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance Industries', index_tier: 'NIFTY50',
      direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'Refiner up.', key_points: [],
      confidence_score: 50, time_horizon: 'Short-Term',
      basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN', in_my_holdings: true, past_mentions: [],
      sector: 'Energy',
    },
    {
      company_id: 2, ticker: 'ONGC.NS', name: 'ONGC', index_tier: 'NIFTYNEXT50',
      direction: 'bearish', magnitude_low: -3, magnitude_high: -1, rationale: 'Cost pressure.', key_points: [],
      confidence_score: 50, time_horizon: 'Short-Term',
      basis: 'sector_inference', confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
      sector: 'Financials',
    },
  ],
};

describe('AlertCompanies', () => {
  it('shows Predicted companies grouped by impact level by default, Direct expanded', () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    expect(screen.getByText(/Direct Impact/)).toBeInTheDocument();
    // Both fixture companies default to impact_level 'direct' (unset), so
    // both land in the one, already-expanded Direct Impact group -- their
    // collapsed row names are visible without any click.
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.getByText('ONGC')).toBeInTheDocument();
  });

  it('filters to held companies on the My Portfolio tab', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    await userEvent.click(screen.getByRole('button', { name: /my portfolio/i }));
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.queryByText('ONGC')).not.toBeInTheDocument();
  });

  it('shows a login prompt on My Portfolio when logged out with no matches', async () => {
    const anon: Alert = { ...alert, companies: alert.companies.map((c) => ({ ...c, in_my_holdings: false })) };
    render(<AlertCompanies alert={anon} isAuthenticated={false} />);
    await userEvent.click(screen.getByRole('button', { name: /my portfolio/i }));
    expect(screen.getByText(/log in to see holdings-matched alerts/i)).toBeInTheDocument();
  });

  it('renders impact-level headings in Direct -> Ripple L1 -> Ripple L2 order', async () => {
    const levelAlert: Alert = {
      ...alert,
      companies: [
        { ...alert.companies[1], company_id: 1, name: 'L2 Co', impact_level: 'indirect_l2' },
        { ...alert.companies[0], company_id: 2, name: 'Direct Co', impact_level: 'direct' },
        { ...alert.companies[1], company_id: 3, name: 'L1 Co', impact_level: 'indirect_l1' },
      ],
    };
    render(<AlertCompanies alert={levelAlert} isAuthenticated />);
    const headings = screen.getAllByText(
      /^(Direct Impact|Indirect Impact — Level 1|Indirect Impact — Level 2)/,
    );
    expect(headings.map((el) => el.textContent)).toEqual([
      expect.stringContaining('Direct Impact'),
      expect.stringContaining('Indirect Impact — Level 1'),
      expect.stringContaining('Indirect Impact — Level 2'),
    ]);
  });

  it('starts Direct Impact expanded and Ripple levels collapsed', () => {
    const levelAlert: Alert = {
      ...alert,
      companies: [
        { ...alert.companies[0], company_id: 1, name: 'Direct Co', impact_level: 'direct' },
        { ...alert.companies[1], company_id: 2, name: 'Ripple Co', impact_level: 'indirect_l1' },
      ],
    };
    render(<AlertCompanies alert={levelAlert} isAuthenticated />);
    expect(screen.getByText('Direct Co')).toBeInTheDocument();
    expect(screen.queryByText('Ripple Co')).not.toBeInTheDocument();
  });

  it('expands a Ripple group on click to reveal its companies', async () => {
    const levelAlert: Alert = {
      ...alert,
      companies: [
        { ...alert.companies[0], company_id: 1, name: 'Direct Co', impact_level: 'direct' },
        { ...alert.companies[1], company_id: 2, name: 'Ripple Co', impact_level: 'indirect_l1' },
      ],
    };
    render(<AlertCompanies alert={levelAlert} isAuthenticated />);
    await userEvent.click(screen.getByText(/Indirect Impact — Level 1/));
    expect(screen.getByText('Ripple Co')).toBeInTheDocument();
  });

  // The group-by selector is commented out in AlertCompanies.tsx (no
  // combobox to drive these anymore) -- skipped, not deleted, to match.
  it.skip('shows Bullish/Bearish group headers with counts when grouped by Impact', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'impact');
    expect(screen.getByText('Bullish · 1')).toBeInTheDocument();
    expect(screen.getByText('Bearish · 1')).toBeInTheDocument();
  });

  it.skip('shows sector group headers with counts when grouped by Sector', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'sector');
    expect(screen.getByText('Energy · 1')).toBeInTheDocument();
    expect(screen.getByText('Financials · 1')).toBeInTheDocument();
  });

  it.skip('mutes sector-inferred companies relative to direct-mention companies when grouped', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'impact');
    expect(screen.getByText('Reliance Industries').closest('.opacity-70')).toBeNull();
    expect(screen.getByText('ONGC').closest('.opacity-70')).not.toBeNull();
  });

  it.skip('shows the empty-state message instead of a blank panel when Impact mode has no groupable companies', async () => {
    const noDirectionAlert: Alert = {
      ...alert,
      companies: alert.companies.map((c) => ({ ...c, direction: 'unknown' })),
    };
    render(<AlertCompanies alert={noDirectionAlert} isAuthenticated />);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'impact');
    expect(screen.getByText('No affected companies for this story.')).toBeInTheDocument();
  });

  it('shows the sentiment bar reflecting the currently visible (tab-filtered) companies', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    expect(screen.getByText('1 Bullish')).toBeInTheDocument();
    expect(screen.getByText('1 Bearish')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /my portfolio/i }));
    expect(screen.getByText('1 Bullish')).toBeInTheDocument();
    expect(screen.getByText('0 Bearish')).toBeInTheDocument();
  });

  it('shows a Charts button that navigates to the charts page when companies are visible', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    const chartsButton = screen.getByRole('button', { name: /charts/i });
    expect(chartsButton).toBeInTheDocument();
    await userEvent.click(chartsButton);
    expect(mockNavigate).toHaveBeenCalledWith('/alerts/1/charts');
  });

  it('hides the Charts button when the active tab has no visible companies', async () => {
    const anon: Alert = { ...alert, companies: alert.companies.map((c) => ({ ...c, in_my_holdings: false })) };
    render(<AlertCompanies alert={anon} isAuthenticated={false} />);
    await userEvent.click(screen.getByRole('button', { name: /my portfolio/i }));
    expect(screen.queryByRole('button', { name: /charts/i })).not.toBeInTheDocument();
  });

  it('does not render a List/Chart toggle anymore', () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    expect(screen.queryByRole('button', { name: 'List' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Chart' })).not.toBeInTheDocument();
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
  });

  it('ArrowRight navigates to charts when no input has focus', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    mockNavigate.mockClear();

    // Simulate ArrowRight keypress with no focused element
    const event = new KeyboardEvent('keydown', { key: 'ArrowRight' });
    document.dispatchEvent(event);

    expect(mockNavigate).toHaveBeenCalledWith('/alerts/1/charts');
  });

  it('renders a "Read full analysis" link for each company once expanded, routing to its detail page', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    // Both fixture companies default to impact_level 'direct', collapsed to
    // a name-only row until clicked -- expand each before the link exists.
    await userEvent.click(screen.getByText('Reliance Industries'));
    await userEvent.click(screen.getByText('ONGC'));
    const links = screen.getAllByRole('link', { name: /read full analysis/i });
    const hrefs = links.map((link) => link.getAttribute('href'));
    expect(hrefs).toContain('/alerts/1/company/1');
    expect(hrefs).toContain('/alerts/1/company/2');
  });

  it('ArrowRight does NOT navigate when an input element has focus', async () => {
    render(<AlertCompanies alert={alert} isAuthenticated />);
    mockNavigate.mockClear();

    // Create and focus an input element
    const input = document.createElement('input');
    input.type = 'text';
    document.body.appendChild(input);
    input.focus();

    // Simulate ArrowRight keypress with input focused
    const event = new KeyboardEvent('keydown', { key: 'ArrowRight' });
    document.dispatchEvent(event);

    expect(mockNavigate).not.toHaveBeenCalled();

    // Cleanup
    document.body.removeChild(input);
  });

});