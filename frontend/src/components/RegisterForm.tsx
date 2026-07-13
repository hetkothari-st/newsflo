import { useState, type FormEvent } from 'react';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';

export default function RegisterForm({ onSuccess }: { onSuccess?: () => void }) {
  const { register } = useAuth();
  const { t } = useLanguage();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email) {
      setError(t('auth.registerMissing'));
      return;
    }
    if (password.length < 6) {
      setError(t('auth.passwordTooShort'));
      return;
    }
    setSubmitting(true);
    try {
      await register(email, password);
      onSuccess?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('auth.registerFailed'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" aria-label={t('auth.registerFormAria')}>
      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-widest text-muted">{t('auth.emailLabel')}</span>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded-lg border border-hairline bg-surface px-3 py-2 text-ink outline-none focus:border-muted theme-light:border-transparent theme-light:shadow-neu-inset"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-widest text-muted">{t('auth.passwordLabel')}</span>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="rounded-lg border border-hairline bg-surface px-3 py-2 text-ink outline-none focus:border-muted theme-light:border-transparent theme-light:shadow-neu-inset"
        />
      </label>
      {error && <p role="alert" className="text-xs text-bearish">{error}</p>}
      <button
        type="submit"
        disabled={submitting}
        className="rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50 theme-light:border-transparent theme-light:bg-accent theme-light:text-page theme-light:shadow-neu"
      >
        {submitting ? t('auth.creating') : t('auth.createAccount')}
      </button>
    </form>
  );
}
