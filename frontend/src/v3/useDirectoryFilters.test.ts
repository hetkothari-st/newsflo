import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { DirectoryCompany } from './api';
import { useDirectoryFilters } from './useDirectoryFilters';

function company(overrides: Partial<DirectoryCompany>): DirectoryCompany {
  return {
    ticker: 'RELIANCE.NS',
    name: 'Reliance Industries',
    sector: 'oil_gas',
    cap_tier: 'LARGE',
    logo_url: null,
    market_cap: 1000,
    index_tier: 'NIFTY50',
    sub_sector: 'refining_marketing',
    pe: 25.0,
    pb: 2.5,
    roe: 12.0,
    website_domain: null,
    ...overrides,
  };
}

const LIST = [
  company({ ticker: 'A.NS', sector: 'it', sub_sector: 'services' }),
  company({ ticker: 'B.NS', sector: 'oil_gas', sub_sector: 'refining_marketing' }),
];

describe('useDirectoryFilters', () => {
  it('derives option lists and full result from companies', () => {
    const { result } = renderHook(() => useDirectoryFilters(LIST));
    expect(result.current.sectors).toEqual(['ALL', 'it', 'oil_gas']);
    expect(result.current.subSectors).toEqual([]);
    expect(result.current.filtered).toHaveLength(2);
  });

  it('handles null companies (not yet loaded)', () => {
    const { result } = renderHook(() => useDirectoryFilters(null));
    expect(result.current.filtered).toEqual([]);
    expect(result.current.sectors).toEqual(['ALL']);
  });

  it('changing sector resets the sub-sector', () => {
    const { result } = renderHook(() => useDirectoryFilters(LIST));
    act(() => result.current.patchFilters({ sector: 'it' }));
    act(() => result.current.patchFilters({ subSector: 'services' }));
    expect(result.current.filters.subSector).toBe('services');
    act(() => result.current.patchFilters({ sector: 'oil_gas' }));
    expect(result.current.filters.subSector).toBe('ALL');
  });

  it('re-selecting the same sector keeps the sub-sector', () => {
    const { result } = renderHook(() => useDirectoryFilters(LIST));
    act(() => result.current.patchFilters({ sector: 'it' }));
    act(() => result.current.patchFilters({ subSector: 'services' }));
    act(() => result.current.patchFilters({ sector: 'it' }));
    expect(result.current.filters.subSector).toBe('services');
  });

  it('filtered recomputes on filter patches', () => {
    const { result } = renderHook(() => useDirectoryFilters(LIST));
    act(() => result.current.patchFilters({ search: 'a.ns' }));
    expect(result.current.filtered.map((c) => c.ticker)).toEqual(['A.NS']);
  });
});
