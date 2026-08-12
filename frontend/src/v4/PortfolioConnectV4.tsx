/* Broker connect panel: a ruled directory of Indian providers. Every
   provider connects through the format-agnostic holdings-file import;
   brokers with a live connector (Zerodha, Upstox, Fyers, Angel One,
   ICICI Direct via redirect; Dhan via pasted token) additionally offer
   it when the server is configured for them. Redirect callbacks land in
   PortfolioV4, which posts the params to the provider import. */
import { useEffect, useRef, useState } from 'react';
import { BROKERS, type Broker } from './brokers';
import {
  getConnectStatus,
  getProviderLoginUrl,
  importHoldingsFile,
  providerImport,
  type ConnectStatus,
  type ImportReport,
} from './portfolioApi';

export default function PortfolioConnectV4({
  token,
  onImported,
}: {
  token: string;
  onImported: () => void;
}) {
  const [selected, setSelected] = useState<Broker | null>(null);
  const [status, setStatus] = useState<ConnectStatus | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pasteToken, setPasteToken] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getConnectStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  const pick = (broker: Broker) => {
    setSelected(broker.slug === selected?.slug ? null : broker);
    setReport(null);
    setError(null);
    setPasteToken('');
  };

  const finish = (result: ImportReport) => {
    setReport(result);
    if (result.imported.length > 0) onImported();
  };

  const upload = async (file: File) => {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      finish(await importHoldingsFile(token, file));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed — try again.');
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const connectLive = async (provider: string) => {
    try {
      window.location.href = await getProviderLoginUrl(token, provider);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Live connect unavailable.');
    }
  };

  const importToken = async (provider: string) => {
    if (!pasteToken.trim()) return;
    setBusy(true);
    setError(null);
    try {
      finish(await providerImport(token, provider, { access_token: pasteToken.trim() }));
      setPasteToken('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed — try again.');
    } finally {
      setBusy(false);
    }
  };

  const liveSlug = selected?.live;
  const liveConfigured = liveSlug !== undefined && status?.providers[liveSlug] === true;
  const liveFlow = liveSlug !== undefined ? status?.flows[liveSlug] : undefined;

  return (
    <div className="connect4">
      <p className="psub">
        Pick your provider. Every broker's console exports a holdings file — drop it here and the
        positions land in your portfolio. Brokers with a live API also connect directly.
      </p>
      <div className="brokergrid">
        {BROKERS.map((broker) => (
          <button
            key={broker.slug}
            type="button"
            className={`brokercell ${selected?.slug === broker.slug ? 'on' : ''}`}
            onClick={() => pick(broker)}
          >
            {broker.name}
            {broker.live !== undefined && status?.providers[broker.live] === true && (
              <span className="livedot" aria-label="live connect available" />
            )}
          </button>
        ))}
      </div>
      {selected !== null && (
        <div className="brokerpanel">
          <h3>{selected.name}</h3>
          <p className="psub">{selected.hint}</p>
          {liveSlug !== undefined && liveFlow === 'redirect' && (
            <button
              type="button"
              className="authsubmit"
              disabled={!liveConfigured}
              title={liveConfigured ? undefined : `Server has no ${selected.name} API keys configured`}
              onClick={() => void connectLive(liveSlug)}
            >
              {liveConfigured ? `Connect live via ${selected.name} →` : 'Live connect unavailable — use CSV'}
            </button>
          )}
          {liveSlug !== undefined && liveFlow === 'token' && (
            <div className="tokenrow">
              <input
                type="password"
                placeholder="Paste access token"
                aria-label={`${selected.name} access token`}
                value={pasteToken}
                onChange={(event) => setPasteToken(event.target.value)}
              />
              <button
                type="button"
                className="authsubmit"
                disabled={busy || pasteToken.trim() === ''}
                onClick={() => void importToken(liveSlug)}
              >
                Import →
              </button>
            </div>
          )}
          <label className="filedrop">
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              disabled={busy}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
              }}
            />
            <span>{busy ? 'Importing…' : 'Drop or choose the holdings CSV'}</span>
          </label>
        </div>
      )}
      {error !== null && <p className="autherr">{error}</p>}
      {report !== null && (
        <div className="importreport">
          <p>
            Imported {report.imported.length} holding{report.imported.length === 1 ? '' : 's'}
            {report.skipped.length > 0 ? ` — ${report.skipped.length} skipped` : ''}.
          </p>
          {report.skipped.slice(0, 8).map((skip) => (
            <p className="skiprow" key={`${skip.row}-${skip.reason}`}>
              {skip.row || '(row)'} — {skip.reason}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
