import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import type { TranslationKey } from '../lib/i18n';
import { useLanguage } from '../lib/language';

const LINKS: { to: string; labelKey: TranslationKey }[] = [
  { to: '/', labelKey: 'nav.feed' },
  { to: '/holdings', labelKey: 'nav.holdings' },
];

export default function BottomNav({ onOpenCalendar }: { onOpenCalendar: () => void }) {
  const { pathname } = useLocation();
  const { token } = useAuth();
  const { t } = useLanguage();

  const itemClass = (activeCondition: boolean) =>
    `flex flex-1 items-center justify-center text-xs uppercase tracking-widest ${
      activeCondition ? 'text-ink' : 'text-muted'
    }`;

  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex h-14 border-t border-hairline bg-page md:hidden">
      {LINKS.map((l) => (
        <Link key={l.to} to={l.to} className={itemClass(pathname === l.to)}>
          {t(l.labelKey)}
        </Link>
      ))}
      <button type="button" onClick={onOpenCalendar} className={itemClass(false)}>
        {t('nav.calendar')}
      </button>
      <Link
        to={token ? '/account' : '/login'}
        className={itemClass(pathname === '/account' || pathname === '/login')}
      >
        {t('nav.account')}
      </Link>
    </nav>
  );
}
