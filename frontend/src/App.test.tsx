import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { AuthProvider } from './lib/auth';
import { LanguageProvider } from './lib/language';
import { ThemeProvider } from './lib/theme';

// Minimal no-op WebSocket + empty fetch so the (later) live FeedPage mounts
// cleanly inside these routing tests without touching the network.
class NoopSocket {
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  close() {}
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [] } as unknown as Response),
  );
  vi.stubGlobal('WebSocket', NoopSocket as unknown as typeof WebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ThemeProvider>
        <LanguageProvider>
          <AuthProvider>
            <App />
          </AuthProvider>
        </LanguageProvider>
      </ThemeProvider>
    </MemoryRouter>,
  );
}

describe('App routing', () => {
  it('renders the card-feed shell at /', () => {
    renderAt('/');
    // The shell's own bottom nav (spec v2 §7) -- buttons, not router links.
    expect(screen.getByRole('button', { name: /^feed$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /discover/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /directory/i })).toBeInTheDocument();
  });

  it('redirects /holdings to /login when logged out', () => {
    renderAt('/holdings');
    expect(screen.getByRole('heading', { name: /log in/i })).toBeInTheDocument();
  });

  it('renders the holdings page at /holdings when logged in', () => {
    localStorage.setItem('newsflo.token', 'tok');
    localStorage.setItem('newsflo.email', 'me@example.com');
    renderAt('/holdings');
    expect(screen.getByRole('heading', { name: /holdings/i })).toBeInTheDocument();
  });
});
