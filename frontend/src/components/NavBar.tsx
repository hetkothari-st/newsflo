import { Link } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
import LanguagePicker from './LanguagePicker';
import ThemeToggle from './ThemeToggle';

export default function NavBar() {
  const { token } = useAuth();
  const { t } = useLanguage();
  return (
    <nav className="border-b border-hairline bg-page">
      <div className="mx-auto flex min-h-14 max-w-feed items-center justify-between px-4 py-3 md:h-auto md:py-4">
        <Link to="/" className="font-display text-lg font-bold text-ink">
          NewsFlo
        </Link>
        <div className="hidden items-center gap-6 md:flex">
          <Link to="/" className="text-xs uppercase tracking-widest text-muted hover:text-ink">
            {t('nav.feed')}
          </Link>
          <Link to="/holdings" className="text-xs uppercase tracking-widest text-muted hover:text-ink">
            {t('nav.holdings')}
          </Link>
        </div>
        <div className="flex items-center gap-4 text-xs uppercase tracking-widest">
          <LanguagePicker />
          <ThemeToggle />
          <div className="hidden items-center gap-4 md:flex">
            {token ? (
              <Link to="/account" className="text-ink hover:text-muted">
                {t('nav.account')}
              </Link>
            ) : (
              <>
                <Link to="/login" className="text-ink hover:text-muted">
                  {t('nav.login')}
                </Link>
                <Link to="/register" className="text-ink hover:text-muted">
                  {t('nav.register')}
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
