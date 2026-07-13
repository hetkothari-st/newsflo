import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import FeedPage from './FeedPage';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';

vi.mock('../lib/useAlertsSocket', () => ({ useAlertsSocket: () => ({ alerts: [], connected: true }) }));

afterEach(() => {
  vi.restoreAllMocks();
});

describe('FeedPage', () => {
  it('renders the feed with category tabs', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([]);
    render(
      <MemoryRouter>
        <AuthProvider>
          <FeedPage />
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByRole('tab', { name: /india/i })).toBeInTheDocument();
  });
});
