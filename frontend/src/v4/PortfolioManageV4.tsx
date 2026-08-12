/* Holdings manager: ruled list with editable quantities, per-row
   remove, and an add-by-ticker row. Backend upserts by (user, company),
   so save is idempotent; onChanged tells PortfolioV4 to refresh the
   news overlay after any mutation. */
import { useCallback, useEffect, useState } from 'react';
import {
  deleteHolding,
  getHoldingRows,
  saveHolding,
  type HoldingRow,
} from './portfolioApi';

export default function PortfolioManageV4({
  token,
  version,
  onChanged,
}: {
  token: string;
  // Bumped by the parent when an import lands -- triggers a re-fetch.
  version: number;
  onChanged: () => void;
}) {
  const [rows, setRows] = useState<HoldingRow[] | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [newTicker, setNewTicker] = useState('');
  const [newQty, setNewQty] = useState('');
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    getHoldingRows(token)
      .then(setRows)
      .catch((err: Error) => setError(err.message));
  }, [token]);

  useEffect(() => {
    refresh();
  }, [refresh, version]);

  const act = async (run: () => Promise<void>) => {
    setError(null);
    try {
      await run();
      refresh();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Update failed.');
    }
  };

  const saveRow = (row: HoldingRow) => {
    const raw = edits[row.ticker];
    if (raw === undefined) return;
    const quantity = Number(raw);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      setError(`Quantity for ${row.ticker} must be a positive number.`);
      return;
    }
    if (quantity === row.quantity) return;
    void act(() => saveHolding(token, row.ticker, quantity));
  };

  const addRow = (event: React.FormEvent) => {
    event.preventDefault();
    const ticker = newTicker.trim().toUpperCase();
    const quantity = Number(newQty);
    if (!ticker || !Number.isFinite(quantity) || quantity <= 0) {
      setError('Enter a ticker (e.g. RELIANCE.NS) and a positive quantity.');
      return;
    }
    void act(async () => {
      await saveHolding(token, ticker, quantity);
      setNewTicker('');
      setNewQty('');
    });
  };

  return (
    <div className="manage4">
      <h2 className="archsub">Your holdings</h2>
      {rows !== null && rows.length === 0 && (
        <p className="psub">Nothing held yet — add a position below or connect a broker.</p>
      )}
      {(rows ?? []).map((row) => (
        <div className="mrow" key={row.ticker}>
          <span className="mname">{row.name}</span>
          <span className="mtick">{row.ticker}</span>
          <input
            type="number"
            inputMode="decimal"
            aria-label={`Quantity for ${row.ticker}`}
            defaultValue={row.quantity}
            onChange={(event) => setEdits((prev) => ({ ...prev, [row.ticker]: event.target.value }))}
            onBlur={() => saveRow(row)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') (event.target as HTMLInputElement).blur();
            }}
          />
          <button
            type="button"
            className="mdel"
            aria-label={`Remove ${row.ticker}`}
            onClick={() => void act(() => deleteHolding(token, row.ticker))}
          >
            ✕
          </button>
        </div>
      ))}
      <form className="mrow madd" onSubmit={addRow}>
        <input
          type="text"
          aria-label="New holding ticker"
          placeholder="Ticker (RELIANCE.NS)"
          value={newTicker}
          onChange={(event) => setNewTicker(event.target.value)}
        />
        <input
          type="number"
          inputMode="decimal"
          aria-label="New holding quantity"
          placeholder="Qty"
          value={newQty}
          onChange={(event) => setNewQty(event.target.value)}
        />
        <button type="submit" className="authsubmit">
          Add →
        </button>
      </form>
      {error !== null && <p className="autherr">{error}</p>}
    </div>
  );
}
