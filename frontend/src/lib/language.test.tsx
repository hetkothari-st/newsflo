import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { LanguageProvider, useLanguage } from './language';

function wrapper({ children }: { children: ReactNode }) {
  return <LanguageProvider>{children}</LanguageProvider>;
}

afterEach(() => {
  localStorage.clear();
});

describe('LanguageProvider / useLanguage', () => {
  it('defaults to English when nothing is saved', () => {
    const { result } = renderHook(() => useLanguage(), { wrapper });
    expect(result.current.language).toBe('en');
  });

  it('respects an existing saved language on init', () => {
    localStorage.setItem('newsflo.lang', 'hi');
    const { result } = renderHook(() => useLanguage(), { wrapper });
    expect(result.current.language).toBe('hi');
  });

  it('falls back to English for an unsupported saved value', () => {
    localStorage.setItem('newsflo.lang', 'xx');
    const { result } = renderHook(() => useLanguage(), { wrapper });
    expect(result.current.language).toBe('en');
  });

  it('setLanguage updates the value and persists it', () => {
    const { result } = renderHook(() => useLanguage(), { wrapper });

    act(() => result.current.setLanguage('mr'));

    expect(result.current.language).toBe('mr');
    expect(localStorage.getItem('newsflo.lang')).toBe('mr');
  });

  it('t() translates through the current language, falling back to English for a missing key', () => {
    const { result } = renderHook(() => useLanguage(), { wrapper });
    expect(result.current.t('nav.feed')).toBe('Feed');

    act(() => result.current.setLanguage('hi'));
    expect(result.current.t('nav.feed')).toBe('फ़ीड');
  });

  it('throws when used outside a LanguageProvider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => renderHook(() => useLanguage())).toThrow('useLanguage must be used within a LanguageProvider');
    spy.mockRestore();
  });
});
