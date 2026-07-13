import { useState, type FormEvent } from 'react';
import { addHolding, type Holding } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';

export default function HoldingsForm({ onAdded }: { onAdded: (holding: Holding) => void }) {
  const { token } = useAuth();
  const { t } = useLanguage();
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
      setError(t('holdings.addError'));
      return;
    }
    setSubmitting(true);
    try {
      const holding = await addHolding(token, ticker.trim(), qty);
      onAdded(holding);
      setTicker('');
      setQuantity('');
    } catch (err) {
      setError(err instanceof Error ? err.message : t('holdings.addFailed'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row sm:items-end" aria-label={t('holdings.addFormAria')}>
      <label className="flex flex-1 flex-col gap-1">
        <span className="text-xs uppercase tracking-widest text-muted">{t('holdings.ticker')}</span>
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="RELIANCE.NS"
          className="rounded-lg border border-hairline bg-surface px-3 py-2 text-ink outline-none focus:border-muted theme-light:border-transparent theme-light:shadow-neu-inset"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-widest text-muted">{t('holdings.quantity')}</span>
        <input
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          inputMode="decimal"
          className="rounded-lg border border-hairline bg-surface px-3 py-2 text-ink tabular-nums outline-none focus:border-muted theme-light:border-transparent theme-light:shadow-neu-inset"
        />
      </label>
      {error && <p role="alert" className="text-xs text-bearish">{error}</p>}
      <button
        type="submit"
        disabled={submitting}
        className="rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50 theme-light:border-transparent theme-light:bg-accent theme-light:text-page theme-light:shadow-neu"
      >
        {t('holdings.add')}
      </button>
    </form>
  );
}
