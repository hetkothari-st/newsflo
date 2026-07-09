import { useState, type FormEvent } from 'react';
import { useAuth } from '../lib/auth';

export default function RegisterForm({ onSuccess }: { onSuccess?: () => void }) {
  const { register } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email) {
      setError('Enter your email.');
      return;
    }
    if (password.length < 6) {
      setError('Password must be at least 6 characters.');
      return;
    }
    setSubmitting(true);
    try {
      await register(email, password);
      onSuccess?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" aria-label="Register">
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
        {submitting ? 'Creating…' : 'Create account'}
      </button>
    </form>
  );
}
