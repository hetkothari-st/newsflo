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
    // Numbered mono rail 01-10.
    for (let i = 1; i <= 10; i++) {
      expect(screen.getByRole('tab', { name: String(i).padStart(2, '0') })).toBeInTheDocument();
    }
    expect(screen.getByText('← swipe between charts →')).toBeInTheDocument();
  });

  it('renders all ten chart titles in doc order', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alertFixture());
    renderPage('1');
    await waitFor(() => expect(screen.getByText('Impact Tree')).toBeInTheDocument());
    for (const title of [
      'Impact Tree', 'Ripple Effect', 'Supply Chain', 'Multi-Level Tree', 'Confidence Tree',
      'Positive / Negative Split', 'Timeline Tree', 'Sector Tree', 'Economic Chain', 'Knowledge Graph',
    ]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
  });

  it('synthesizes a fallback graph for a legacy alert with no graph block (never blank)', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alertFixture({ graph: undefined }));
    renderPage('1');
    // Economic Chain: legacy graph has no mechanism nodes -> honest empty
    // state rather than a silent blank.
    await waitFor(() =>
      expect(screen.getByText(/No general transmission mechanism applies/)).toBeInTheDocument(),
    );
  });

  it('shows the error state when the fetch fails', async () => {
    vi.spyOn(api, 'getAlert').mockRejectedValue(new Error('boom'));
    renderPage('1');
    await waitFor(() => expect(screen.getByText('boom')).toBeInTheDocument());
  });
});
