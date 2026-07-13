import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { ThemeProvider, useTheme } from './theme';

function wrapper({ children }: { children: ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>;
}

afterEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove('light');
});

describe('ThemeProvider / useTheme', () => {
  it('defaults to dark when nothing is saved', () => {
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.theme).toBe('dark');
    expect(document.documentElement.classList.contains('light')).toBe(false);
  });

  it('respects an existing saved theme on init', () => {
    localStorage.setItem('newsflo.theme', 'light');
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.theme).toBe('light');
    expect(document.documentElement.classList.contains('light')).toBe(true);
  });

  it('toggleTheme flips the value, persists it, and updates the <html> class', () => {
    const { result } = renderHook(() => useTheme(), { wrapper });

    act(() => result.current.toggleTheme());
    expect(result.current.theme).toBe('light');
    expect(localStorage.getItem('newsflo.theme')).toBe('light');
    expect(document.documentElement.classList.contains('light')).toBe(true);

    act(() => result.current.toggleTheme());
    expect(result.current.theme).toBe('dark');
    expect(localStorage.getItem('newsflo.theme')).toBe('dark');
    expect(document.documentElement.classList.contains('light')).toBe(false);
  });

  it('throws when used outside a ThemeProvider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => renderHook(() => useTheme())).toThrow('useTheme must be used within a ThemeProvider');
    spy.mockRestore();
  });
});
