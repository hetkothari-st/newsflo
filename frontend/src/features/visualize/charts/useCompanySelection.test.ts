import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useCompanySelection } from './useCompanySelection';
import type { AlertCompany } from '../../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because it matters here',
    key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('useCompanySelection', () => {
  it('starts with nothing selected', () => {
    const companies = [company({ company_id: 1 })];
    const { result } = renderHook(() => useCompanySelection(companies));
    expect(result.current.selectedId).toBeNull();
    expect(result.current.selected).toBeNull();
  });

  it('selects the company matching the toggled id', () => {
    const companies = [company({ company_id: 1, ticker: 'AAA' }), company({ company_id: 2, ticker: 'BBB' })];
    const { result } = renderHook(() => useCompanySelection(companies));

    act(() => result.current.toggle(2));

    expect(result.current.selectedId).toBe(2);
    expect(result.current.selected?.ticker).toBe('BBB');
  });

  it('toggling the same id again clears the selection', () => {
    const companies = [company({ company_id: 1 })];
    const { result } = renderHook(() => useCompanySelection(companies));

    act(() => result.current.toggle(1));
    expect(result.current.selectedId).toBe(1);

    act(() => result.current.toggle(1));
    expect(result.current.selectedId).toBeNull();
    expect(result.current.selected).toBeNull();
  });

  it('toggling a different id switches the selection', () => {
    const companies = [company({ company_id: 1 }), company({ company_id: 2, ticker: 'BBB' })];
    const { result } = renderHook(() => useCompanySelection(companies));

    act(() => result.current.toggle(1));
    act(() => result.current.toggle(2));

    expect(result.current.selectedId).toBe(2);
    expect(result.current.selected?.ticker).toBe('BBB');
  });

  it('returns null for selected when the selected id is not present in companies', () => {
    const companies = [company({ company_id: 1 })];
    const { result } = renderHook(() => useCompanySelection(companies));

    act(() => result.current.toggle(999));

    expect(result.current.selectedId).toBe(999);
    expect(result.current.selected).toBeNull();
  });
});
