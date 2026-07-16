import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  addHolding,
  getAlerts,
  getCategories,
  getCompanies,
  getCompanyHistory,
  getCompanyLivePrice,
  getCompanyPrices,
  getCompanyProfile,
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
    expect(url).toBe('/api/alerts?lang=en');
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
    const body = [{ category: 'banking', label: 'banking' }, { category: 'oil_energy', label: 'oil_energy' }];
    const fetchMock = mockFetchOnce(body);
    const result = await getCategories();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/categories?lang=en');
    expect(result).toEqual(body);
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

  it('getCompanyProfile fetches the profile endpoint with lang', async () => {
    const body = { id: 1, ticker: 'RELIANCE.NS', latest_alert: null, track_record: null };
    const fetchMock = mockFetchOnce(body);
    const result = await getCompanyProfile(1);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/companies/1/profile?lang=en');
    expect(result).toEqual(body);
  });

  it('getCompanyProfile resolves null on a 404 instead of throwing', async () => {
    mockFetchOnce({ detail: 'Company not found' }, false, 404);
    const result = await getCompanyProfile(999);
    expect(result).toBeNull();
  });

  it('getCompanyHistory fetches with default limit and no cursor', async () => {
    const fetchMock = mockFetchOnce({ mentions: [], has_more: false });
    await getCompanyHistory(1);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/companies/1/history?limit=20');
  });

  it('getCompanyHistory includes the before cursor when given', async () => {
    const fetchMock = mockFetchOnce({ mentions: [], has_more: false });
    await getCompanyHistory(1, '2026-01-01T00:00:00+00:00', 5);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/companies/1/history?limit=5&before=2026-01-01T00%3A00%3A00%2B00%3A00');
  });

  it('getCompanyPrices fetches with the given period', async () => {
    const fetchMock = mockFetchOnce({ period: '1mo', points: [], available: true });
    await getCompanyPrices(1, '1mo');
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/companies/1/prices?period=1mo');
  });

  it('getCompanyLivePrice fetches the live-price endpoint', async () => {
    const fetchMock = mockFetchOnce({ ltp: 2530.0, change_pct: 1.2, as_of: '2026-07-15T09:30:00+00:00', available: true });
    const result = await getCompanyLivePrice(1);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/companies/1/live-price');
    expect(result.ltp).toBe(2530.0);
  });

  it('getCompanyLivePrice bypasses the HTTP cache so polling sees fresh prices', async () => {
    // Regression test: without this, repeat fetch() calls to the same URL
    // within one page session can be served from the browser's HTTP cache,
    // freezing the displayed price until a hard reload.
    const fetchMock = mockFetchOnce({ ltp: 2530.0, change_pct: 1.2, as_of: '2026-07-15T09:30:00+00:00', available: true });
    await getCompanyLivePrice(1);
    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(opts.cache).toBe('no-store');
  });
});
