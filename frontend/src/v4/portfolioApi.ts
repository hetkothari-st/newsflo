/* Portfolio-management API helpers for the v4 shell: holdings CRUD,
   provider-file import, and the Kite Connect flow. Kept v4-local (not
   in v3/api.ts) -- these back v4-only UI. */

export interface HoldingRow {
  company_id: number;
  ticker: string;
  name: string;
  quantity: number;
}

export interface ImportReport {
  imported: Array<{ ticker: string; name: string; quantity: number }>;
  skipped: Array<{ row: string; reason: string }>;
}

function authHeaders(token: string | null): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function expectOk(res: Response): Promise<Response> {
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* keep generic */
    }
    throw new Error(detail);
  }
  return res;
}

export async function getHoldingRows(token: string): Promise<HoldingRow[]> {
  const res = await expectOk(await fetch('/api/holdings', { headers: authHeaders(token) }));
  return (await res.json()) as HoldingRow[];
}

export async function saveHolding(token: string, ticker: string, quantity: number): Promise<void> {
  await expectOk(
    await fetch('/api/holdings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify({ ticker, quantity }),
    }),
  );
}

export async function deleteHolding(token: string, ticker: string): Promise<void> {
  await expectOk(
    await fetch(`/api/holdings/${encodeURIComponent(ticker)}`, {
      method: 'DELETE',
      headers: authHeaders(token),
    }),
  );
}

export async function importHoldingsFile(token: string, file: File): Promise<ImportReport> {
  const form = new FormData();
  form.append('file', file);
  const res = await expectOk(
    await fetch('/api/holdings/import', {
      method: 'POST',
      headers: authHeaders(token),
      body: form,
    }),
  );
  return (await res.json()) as ImportReport;
}

export async function getConnectStatus(): Promise<{ kite_configured: boolean }> {
  const res = await expectOk(await fetch('/api/portfolio/connect/status'));
  return (await res.json()) as { kite_configured: boolean };
}

export async function getKiteLoginUrl(token: string): Promise<string> {
  const res = await expectOk(
    await fetch('/api/portfolio/connect/kite/login-url', { headers: authHeaders(token) }),
  );
  return ((await res.json()) as { url: string }).url;
}

export async function kiteImport(token: string, requestToken: string): Promise<ImportReport> {
  const res = await expectOk(
    await fetch('/api/portfolio/connect/kite/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify({ request_token: requestToken }),
    }),
  );
  return (await res.json()) as ImportReport;
}
