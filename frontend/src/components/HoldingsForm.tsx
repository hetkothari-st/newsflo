import { useState, type FormEvent } from 'react';
import { addHolding, type Holding } from '../lib/api';
import { useAuth } from '../lib/auth';

export default function HoldingsForm({ onAdded }: { onAdded: (holding: Holding) => void }) {
  const { token } = useAuth();
  const [ticker, setTicker] = useState('');
  const [quantity, setQuantity] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!token) return;
    const qty = Number(quantity);
    if (!ticker.trim() || !Number.isFinite(qty) || qty <= 0) {
      setError('Enter a ticker and a positive quantity.');
      return;
    }
    setSubmitting(true);
    try {
      const holding = await addHolding(token, ticker.trim(), qty);
      onAdded(holding);
      setTicker('');
      setQuantity('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add holding.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row sm:items-end" aria-label="Add holding">
      <label className="flex flex-1 flex-col gap-1">
        <span className="text-xs uppercase tracking-widest text-muted">Ticker</span>
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="RELIANCE.NS"
          className="rounded-lg border border-hairline bg-surface px-3 py-2 text-ink outline-none focus:border-muted"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-widest text-muted">Quantity</span>
        <input
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          inputMode="decimal"
          className="rounded-lg border border-hairline bg-surface px-3 py-2 text-ink tabular-nums outline-none focus:border-muted"
        />
      </label>
      {error && <p role="alert" className="text-xs text-bearish">{error}</p>}
      <button
        type="submit"
        disabled={submitting}
        className="rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50"
      >
        Add
      </button>
    </form>
  );
}
