/* Broker connect panel: a ruled directory of Indian providers. Every
   provider connects through the format-agnostic holdings-file import
   (the backend parser reads any console's CSV export); Zerodha also
   offers a live Kite Connect import when the server has API keys.
   After Kite's redirect lands back with ?request_token, PortfolioV4
   posts it here via onKiteToken -> kiteImport. */
import { useEffect, useRef, useState } from 'react';
import { BROKERS, type Broker } from './brokers';
import {
  getConnectStatus,
  getKiteLoginUrl,
  importHoldingsFile,
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
  const [kiteConfigured, setKiteConfigured] = useState(false);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getConnectStatus()
      .then((status) => setKiteConfigured(status.kite_configured))
      .catch(() => setKiteConfigured(false));
  }, []);

  const pick = (broker: Broker) => {
    setSelected(broker.slug === selected?.slug ? null : broker);
    setReport(null);
    setError(null);
  };

  const upload = async (file: File) => {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const result = await importHoldingsFile(token, file);
      setReport(result);
      if (result.imported.length > 0) onImported();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed — try again.');
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const connectKite = async () => {
    try {
      window.location.href = await getKiteLoginUrl(token);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Zerodha connect unavailable.');
    }
  };

  return (
    <div className="connect4">
      <p className="psub">
        Pick your provider. Every broker's console exports a holdings file — drop it here and the
        positions land in your portfolio. Zerodha can also connect live.
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
          </button>
        ))}
      </div>
      {selected !== null && (
        <div className="brokerpanel">
          <h3>{selected.name}</h3>
          <p className="psub">{selected.hint}</p>
          {selected.live === 'kite' && (
            <button
              type="button"
              className="authsubmit"
              disabled={!kiteConfigured}
              title={kiteConfigured ? undefined : 'Server has no Kite API keys configured'}
              onClick={connectKite}
            >
              {kiteConfigured ? 'Connect live via Kite →' : 'Live connect unavailable — use CSV'}
            </button>
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
