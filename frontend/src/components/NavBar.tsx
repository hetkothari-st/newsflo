import { Link } from 'react-router-dom';
import { useAuth } from '../lib/auth';

export default function NavBar() {
  const { token, email, logout } = useAuth();
  return (
    <nav className="border-b border-hairline bg-page">
      <div className="mx-auto flex h-14 max-w-feed items-center px-4 md:h-auto md:justify-between md:py-4">
        <Link to="/" className="font-display text-lg font-bold text-ink">
          NewsFlo
        </Link>
        <div className="hidden items-center gap-6 md:flex">
          <Link to="/" className="text-xs uppercase tracking-widest text-muted hover:text-ink">
            Feed
          </Link>
          <Link to="/holdings" className="text-xs uppercase tracking-widest text-muted hover:text-ink">
            Holdings
          </Link>
        </div>
        <div className="hidden items-center gap-4 text-xs uppercase tracking-widest md:flex">
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
