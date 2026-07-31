import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ChartDeckPage from './ChartDeckPage';
import { AuthProvider } from '../../../lib/auth';
import { LanguageProvider } from '../../../lib/language';
import { ThemeProvider } from '../../../lib/theme';
import * as api from '../../../lib/api';
import type { Alert } from '../../../lib/api';
import { article, sparseCompanies } from './fixtures';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

function alertFixture(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 1,
    category: 'macro_policy',
    category_label: 'Macro & Policy',
    created_at: '2026-07-22T10:30:00Z',
    article,
    companies: sparseCompanies,
    event_type: 'repo_rate_change',
    ...overrides,
  };
}

function renderPage(id = '1') {
  return render(
    <ThemeProvider>
      <LanguageProvider>
        <AuthProvider>
          <MemoryRouter initialEntries={[`/alerts/${id}/charts`]}>
            <Routes>
              <Route path="/alerts/:id/charts" element={<ChartDeckPage />} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </LanguageProvider>
    </ThemeProvider>,
  );
}

describe('ChartDeckPage', () => {
  it('fetches the alert and renders the prototype shell: kicker, headline, rail, foot hint', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alertFixture());
    renderPage('1');
    await waitFor(() => expect(screen.getByText('Impact charts')).toBeInTheDocument());
    expect(screen.getByRole('heading', { name: article.title })).toBeInTheDocument();
    // Numbered mono rail: the fixture's synthesized graph has no mechanism
    // nodes, so Economic Chain is hidden -- and the 9 surviving charts
    // renumber SEQUENTIALLY (user rule: a skipped chart must not leave a
    // gap), so the rail reads 01..09 with no 10.
    for (let i = 1; i <= 9; i++) {
      expect(screen.getByRole('tab', { name: String(i).padStart(2, '0') })).toBeInTheDocument();
    }
    expect(screen.queryByRole('tab', { name: '10' })).toBeNull();
    expect(screen.getByText('← swipe between charts →')).toBeInTheDocument();
  });

  it('renders the available chart titles in doc order and hides no-data charts', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alertFixture());
    renderPage('1');
    await waitFor(() => expect(screen.getByText('Impact Tree')).toBeInTheDocument());
    for (const title of [
      'Impact Tree', 'Ripple Effect', 'Supply Chain', 'Multi-Level Tree', 'Confidence Tree',
      'Positive / Negative Split', 'Timeline Tree', 'Sector Tree', 'Knowledge Graph',
    ]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
    // No mechanism chain for this alert -> the chart is not shown at all
    // (user rule: hide, don't render an empty state).
    expect(screen.queryByText('Economic Chain')).toBeNull();
    expect(screen.queryByText(/No general transmission mechanism applies/)).toBeNull();
  });

  it('shows a quiet page-level note when no chart has data', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alertFixture({ companies: [] }));
    renderPage('1');
    await waitFor(() => expect(screen.getByText('No chart data for this alert.')).toBeInTheDocument());
    expect(screen.queryByRole('tab', { name: '01' })).toBeNull();
  });

  it('shows the error state when the fetch fails', async () => {
    vi.spyOn(api, 'getAlert').mockRejectedValue(new Error('boom'));
    renderPage('1');
    await waitFor(() => expect(screen.getByText('boom')).toBeInTheDocument());
  });
});
