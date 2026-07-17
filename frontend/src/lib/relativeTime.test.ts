import { describe, expect, it } from 'vitest';
import { formatRelativeTime } from './relativeTime';

const NOW = new Date('2026-07-17T12:00:00.000Z');

describe('formatRelativeTime', () => {
  it('shows "just now" under 60 seconds', () => {
    expect(formatRelativeTime('2026-07-17T11:59:30.000Z', NOW, 'en')).toBe('just now');
  });

  it('shows minutes at the 60-second boundary', () => {
    expect(formatRelativeTime('2026-07-17T11:59:00.000Z', NOW, 'en')).toBe('1m ago');
  });

  it('shows minutes just under an hour', () => {
    expect(formatRelativeTime('2026-07-17T11:01:00.000Z', NOW, 'en')).toBe('59m ago');
  });

  it('shows hours at the 60-minute boundary', () => {
    expect(formatRelativeTime('2026-07-17T11:00:00.000Z', NOW, 'en')).toBe('1h ago');
  });

  it('shows hours just under a day', () => {
    expect(formatRelativeTime('2026-07-16T13:00:00.000Z', NOW, 'en')).toBe('23h ago');
  });

  it('shows days at the 24-hour boundary', () => {
    expect(formatRelativeTime('2026-07-16T12:00:00.000Z', NOW, 'en')).toBe('1d ago');
  });

  it('shows days just under a week', () => {
    expect(formatRelativeTime('2026-07-11T12:00:00.000Z', NOW, 'en')).toBe('6d ago');
  });

  it('falls back to an absolute date at 7 days and beyond', () => {
    const result = formatRelativeTime('2026-07-10T12:00:00.000Z', NOW, 'en');
    expect(result).not.toMatch(/ago$/);
    expect(result).toContain('Jul');
  });
});
