/* Account page: the one place auth lives. Signed out -> the broadsheet
   sign-in / create-account form; signed in -> a small profile card with
   sign-out. Sections that need auth (Portfolio, Review) send the reader
   here instead of embedding forms. */
import AuthV4 from './AuthV4';
import { useAuth } from '../lib/auth';

export default function AccountV4() {
  const { token, email, logout } = useAuth();

  if (!token) {
    return (
      <div className="page4">
        <AuthV4 purpose="One account for your portfolio, holdings and reaction reviews." />
      </div>
    );
  }

  return (
    <div className="page4">
      <h1 className="phead">Account</h1>
      <p className="psub">Signed in.</p>
      <div className="acctcard">
        <span className="acctmark" aria-hidden="true">
          {(email ?? '?').slice(0, 1).toUpperCase()}
        </span>
        <div className="acctbody">
          <span className="acctname">{email?.split('@')[0]}</span>
          <span className="acctmail">{email}</span>
        </div>
        <button type="button" className="authsubmit" onClick={logout}>
          Sign out
        </button>
      </div>
    </div>
  );
}
