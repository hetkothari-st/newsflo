import { useRef, useState, type ChangeEvent } from 'react';
import { uploadHoldingsCsv } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';

export default function HoldingsCsvUpload({ onUploaded }: { onUploaded: () => void }) {
  const { token } = useAuth();
  const { t } = useLanguage();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !token) return;
    setError(null);
    setStatus(null);
    try {
      const res = await uploadHoldingsCsv(token, file);
      setStatus(t('holdings.csvLoaded', { n: res.loaded }));
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('holdings.uploadFailed'));
    } finally {
      if (inputRef.current) inputRef.current.value = '';
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs uppercase tracking-widest text-muted">{t('holdings.csvLabel')}</span>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv"
        onChange={handleChange}
        aria-label={t('holdings.csvAria')}
        className="text-xs text-muted file:mr-3 file:rounded-lg file:border file:border-hairline file:bg-surface file:px-3 file:py-2 file:text-xs file:uppercase file:tracking-widest file:text-ink"
      />
      {status && <p className="text-xs text-bullish">{status}</p>}
      {error && <p role="alert" className="text-xs text-bearish">{error}</p>}
    </div>
  );
}
