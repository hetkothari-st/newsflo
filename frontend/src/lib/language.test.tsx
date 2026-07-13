import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { LanguageProvider, useLanguage } from './language';
import * as api from './api';

function wrapper({ children }: { children: ReactNode }) {
  return <LanguageProvider>{children}</LanguageProvider>;
}

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
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

  it('setLanguage updates the value and persists it', async () => {
    vi.spyOn(api, 'triggerTranslation').mockResolvedValue({ started: true });
    vi.spyOn(api, 'getTranslationStatus').mockResolvedValue({ total: 0, translated: 0, running: false });
    const { result } = renderHook(() => useLanguage(), { wrapper });

    await act(async () => result.current.setLanguage('mr'));

    expect(result.current.language).toBe('mr');
    expect(localStorage.getItem('newsflo.lang')).toBe('mr');
  });

  it('t() translates through the current language, falling back to English for a missing key', async () => {
    vi.spyOn(api, 'triggerTranslation').mockResolvedValue({ started: true });
    vi.spyOn(api, 'getTranslationStatus').mockResolvedValue({ total: 0, translated: 0, running: false });
    const { result } = renderHook(() => useLanguage(), { wrapper });
    expect(result.current.t('nav.feed')).toBe('Feed');

    await act(async () => result.current.setLanguage('hi'));
    expect(result.current.t('nav.feed')).toBe('फ़ीड');
  });

  it('throws when used outside a LanguageProvider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => renderHook(() => useLanguage())).toThrow('useLanguage must be used within a LanguageProvider');
    spy.mockRestore();
  });

  it('switching to a non-English language triggers a translation drain and tracks progress until done', async () => {
    const trigger = vi.spyOn(api, 'triggerTranslation').mockResolvedValue({ started: true });
    vi.spyOn(api, 'getTranslationStatus').mockResolvedValue({ total: 10, translated: 10, running: false });
    const { result } = renderHook(() => useLanguage(), { wrapper });

    act(() => result.current.setLanguage('hi'));

    expect(result.current.translating).toBe(true);
    expect(trigger).toHaveBeenCalledWith('hi');

    await waitFor(() => expect(result.current.translating).toBe(false));
    expect(result.current.translationProgress).toEqual({ total: 10, translated: 10, running: false });
  });

  it('switching to English does not trigger translation and clears progress', () => {
    const trigger = vi.spyOn(api, 'triggerTranslation');
    const { result } = renderHook(() => useLanguage(), { wrapper });

    act(() => result.current.setLanguage('en'));

    expect(trigger).not.toHaveBeenCalled();
    expect(result.current.translating).toBe(false);
    expect(result.current.translationProgress).toBeNull();
  });

  it('a failed trigger/poll leaves translating false rather than stuck loading forever', async () => {
    vi.spyOn(api, 'triggerTranslation').mockRejectedValue(new Error('network down'));
    const { result } = renderHook(() => useLanguage(), { wrapper });

    act(() => result.current.setLanguage('hi'));
    expect(result.current.translating).toBe(true);

    await waitFor(() => expect(result.current.translating).toBe(false));
  });
});
