import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Feed, { mergeAlerts } from './Feed';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';
import type { Alert } from '../lib/api';

// Isolate Feed from the real socket in these tests.
vi.mock('../lib/useAlertsSocket', () => ({ useAlertsSocket: () => [] }));

function makeAlert(id: number, title: string): Alert {
  return {
    id,
    category: 'oil_energy',
    created_at: '2026-07-09T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}` },
    companies: [],
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('mergeAlerts', () => {
  it('prepends live alerts and dedupes by id (live wins)', () => {
    const merged = mergeAlerts([makeAlert(2, 'two-live')], [makeAlert(1, 'one'), makeAlert(2, 'two')]);
    expect(merged.map((a) => a.id)).toEqual([2, 1]);
    expect(merged[0].article.title).toBe('two-live');
  });
});

describe('Feed', () => {
  it('renders alert cards from the initial fetch', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([makeAlert(1, 'Oil news headline')]);
    render(
      <AuthProvider>
        <Feed />
      </AuthProvider>,
    );
    expect(await screen.findByText('Oil news headline')).toBeInTheDocument();
  });

  it('shows an empty state when there are no alerts', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([]);
    render(
      <AuthProvider>
        <Feed />
      </AuthProvider>,
    );
    expect(await screen.findByText(/no alerts yet/i)).toBeInTheDocument();
  });
});
