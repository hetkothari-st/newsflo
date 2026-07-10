import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import LiveStatus, { formatAgo } from './LiveStatus';

describe('formatAgo', () => {
  const now = new Date('2026-07-10T10:05:00Z').getTime();

  it('reports "just now" for very recent timestamps', () => {
    expect(formatAgo('2026-07-10T10:04:58Z', now)).toBe('just now');
  });
  it('reports seconds for sub-minute gaps', () => {
    expect(formatAgo('2026-07-10T10:04:40Z', now)).toBe('20s ago');
  });
  it('reports minutes for sub-hour gaps', () => {
    expect(formatAgo('2026-07-10T09:50:00Z', now)).toBe('15m ago');
  });
  it('reports hours for sub-day gaps', () => {
    expect(formatAgo('2026-07-10T06:05:00Z', now)).toBe('4h ago');
  });
});

describe('LiveStatus', () => {
  it('shows Live and time-since-last-alert when connected', () => {
    render(<LiveStatus connected lastAlertAt={new Date().toISOString()} />);
    expect(screen.getByText('Live')).toBeInTheDocument();
    expect(screen.getByText('just now')).toBeInTheDocument();
  });

  it('shows Reconnecting when the socket is down', () => {
    render(<LiveStatus connected={false} lastAlertAt={null} />);
    expect(screen.getByText('Reconnecting')).toBeInTheDocument();
  });
});
