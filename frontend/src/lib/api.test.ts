import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  addHolding,
  getAlerts,
  getCategories,
  getCompanies,
  getWatchlist,
  login,
  putWatchlist,
  register,
} from './api';

function mockFetchOnce(body: unknown, ok = true, status = 200) {
  const fn = vi.fn().mockResolvedValue({
    ok,
    status,
    json: async () => body,
  } as Response);
  vi.stubGlobal('fetch', fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('api client', () => {
  it('getAlerts sends no Authorization header when no token is passed', async () => {
    const fetchMock = mockFetchOnce([]);
    await getAlerts();
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/alerts');
    expect((opts.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('getAlerts attaches a Bearer token when provided', async () => {
    const fetchMock = mockFetchOnce([]);
    await getAlerts('tok123');
    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((opts.headers as Record<string, string>).Authorization).toBe('Bearer tok123');
  });

  it('register posts a JSON body and returns the token', async () => {
    const fetchMock = mockFetchOnce({ access_token: 'abc', token_type: 'bearer' });
    const result = await register('a@example.com', 'pw12345');
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/auth/register');
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body as string)).toEqual({ email: 'a@example.com', password: 'pw12345' });
    expect(result.access_token).toBe('abc');
  });

  it('addHolding attaches the Bearer token and posts ticker/quantity', async () => {
    const fetchMock = mockFetchOnce({ company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance', quantity: 5 });
    await addHolding('tok', 'RELIANCE.NS', 5);
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/holdings');
    expect((opts.headers as Record<string, string>).Authorization).toBe('Bearer tok');
    expect(JSON.parse(opts.body as string)).toEqual({ ticker: 'RELIANCE.NS', quantity: 5 });
  });

  it('login throws the backend detail message on error', async () => {
    mockFetchOnce({ detail: 'Invalid email or password' }, false, 401);
    await expect(login('a@example.com', 'wrong')).rejects.toThrow('Invalid email or password');
  });

  it('getCompanies fetches all companies with no query when no market given', async () => {
    const fetchMock = mockFetchOnce([]);
    await getCompanies();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/companies');
  });

  it('getCompanies appends the market query param', async () => {
    const fetchMock = mockFetchOnce([]);
    await getCompanies('IN');
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/companies?market=IN');
  });

  it('getCategories fetches the categories endpoint', async () => {
    const fetchMock = mockFetchOnce(['banking', 'oil_energy']);
    const result = await getCategories();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/categories');
    expect(result).toEqual(['banking', 'oil_energy']);
  });

  it('getWatchlist attaches the Bearer token', async () => {
    const fetchMock = mockFetchOnce({ categories: [], companies: [] });
    await getWatchlist('tok');
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/watchlist');
    expect((opts.headers as Record<string, string>).Authorization).toBe('Bearer tok');
  });

  it('putWatchlist PUTs categories and company_ids with the Bearer token', async () => {
    const fetchMock = mockFetchOnce({ categories: ['oil_energy'], companies: [] });
    await putWatchlist('tok', ['oil_energy'], [7]);
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/watchlist');
    expect(opts.method).toBe('PUT');
    expect((opts.headers as Record<string, string>).Authorization).toBe('Bearer tok');
    expect(JSON.parse(opts.body as string)).toEqual({ categories: ['oil_energy'], company_ids: [7] });
  });
});
