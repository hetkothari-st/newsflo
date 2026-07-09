import { useState, type FormEvent } from 'react';
import { useAuth } from '../lib/auth';

export default function LoginForm({ onSuccess }: { onSuccess?: () => void }) {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email || !password) {
      setError('Enter your email and password.');
      return;
    }
    setSubmitting(true);
    try {
      await login(email, password);
      onSuccess?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" aria-label="Log in">
      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-widest text-muted">Email</span>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded-lg border border-hairline bg-surface px-3 py-2 text-ink outline-none focus:border-muted"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-widest text-muted">Password</span>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="rounded-lg border border-hairline bg-surface px-3 py-2 text-ink outline-none focus:border-muted"
        />
      </label>
      {error && <p role="alert" className="text-xs text-bearish">{error}</p>}
      <button
        type="submit"
        disabled={submitting}
        className="rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50"
      >
        {submitting ? 'Signing in…' : 'Log in'}
      </button>
    </form>
  );
}
