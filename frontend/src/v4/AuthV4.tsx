/* Broadsheet sign-in / create-account page, shown in place of any
   auth-gated section (Portfolio, Review) while signed out. One page,
   two modes -- the toggle re-uses the texttabs scale-emphasis idiom.
   On success the AuthProvider persists the token and the gated section
   renders on the next pass; no navigation away from the v4 shell. */
import { useState } from 'react';
import { useAuth } from '../lib/auth';

export default function AuthV4({ purpose }: { purpose: string }) {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === 'login') await login(email, password);
      else await register(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong — try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="authv4">
      <h1 className="phead">{mode === 'login' ? 'Sign in' : 'Create account'}</h1>
      <p className="psub">{purpose}</p>
      <div className="texttabs">
        <button className={mode === 'login' ? 'on' : ''} onClick={() => setMode('login')}>
          Sign in
        </button>
        <button className={mode === 'register' ? 'on' : ''} onClick={() => setMode('register')}>
          Create account
        </button>
      </div>
      <form className="authform" onSubmit={submit}>
        <label>
          <span className="lab">Email</span>
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label>
          <span className="lab">Password</span>
          <input
            type="password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            required
            minLength={6}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error !== null && <p className="autherr">{error}</p>}
        <button type="submit" className="authsubmit" disabled={busy}>
          {busy ? 'Working…' : mode === 'login' ? 'Sign in →' : 'Create account →'}
        </button>
      </form>
    </div>
  );
}
