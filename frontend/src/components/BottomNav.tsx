import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import AlertDetail from './AlertDetail';

const LINKS = [
  { to: '/', label: 'Feed' },
  { to: '/holdings', label: 'Holdings' },
];

export default function BottomNav() {
  const { pathname } = useLocation();
  const { token, email, logout } = useAuth();
  const [accountOpen, setAccountOpen] = useState(false);

  const itemClass = (activeCondition: boolean) =>
    `flex flex-1 items-center justify-center text-xs uppercase tracking-widest ${
      activeCondition ? 'text-ink' : 'text-muted'
    }`;

  return (
    <>
      <nav className="fixed inset-x-0 bottom-0 z-40 flex h-14 border-t border-hairline bg-page md:hidden">
        {LINKS.map((l) => (
          <Link key={l.to} to={l.to} className={itemClass(pathname === l.to)}>
            {l.label}
          </Link>
        ))}
        {token ? (
          <button type="button" onClick={() => setAccountOpen(true)} className={itemClass(accountOpen)}>
            Account
          </button>
        ) : (
          <Link to="/login" className={itemClass(pathname === '/login')}>
            Account
          </Link>
        )}
      </nav>
      <AlertDetail open={accountOpen} onClose={() => setAccountOpen(false)}>
        <div className="flex flex-col gap-4">
          <p className="text-xs uppercase tracking-widest text-muted">{email}</p>
          <button
            type="button"
            onClick={() => {
              logout();
              setAccountOpen(false);
            }}
            className="self-start rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50 theme-light:border-transparent theme-light:bg-accent theme-light:text-page theme-light:shadow-neu"
          >
            Logout
          </button>
        </div>
      </AlertDetail>
    </>
  );
}
