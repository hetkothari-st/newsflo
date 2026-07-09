import { Link } from 'react-router-dom';
import { useAuth } from '../lib/auth';

export default function NavBar() {
  const { token, email, logout } = useAuth();
  return (
    <nav className="border-b border-hairline bg-page">
      <div className="mx-auto flex max-w-feed items-center justify-between px-4 py-4">
        <div className="flex items-center gap-6">
          <Link to="/" className="font-display text-lg font-bold text-ink">
            NewsFlo
          </Link>
          <Link to="/" className="text-xs uppercase tracking-widest text-muted hover:text-ink">
            Feed
          </Link>
          <Link to="/holdings" className="text-xs uppercase tracking-widest text-muted hover:text-ink">
            Holdings
          </Link>
        </div>
        <div className="flex items-center gap-4 text-xs uppercase tracking-widest">
          {token ? (
            <>
              <span className="text-muted">{email}</span>
              <button type="button" onClick={logout} className="text-ink hover:text-muted">
                Logout
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="text-ink hover:text-muted">
                Login
              </Link>
              <Link to="/register" className="text-ink hover:text-muted">
                Register
              </Link>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
