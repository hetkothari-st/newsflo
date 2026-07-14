import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  changePassword,
  deleteAccount,
  getMe,
  updatePreferences,
  type Profile,
} from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
import LanguagePicker from '../components/LanguagePicker';
import ThemeToggle from '../components/ThemeToggle';
import WatchlistSettings from '../components/WatchlistSettings';

function formatMemberSince(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

export default function AccountPage() {
  const { token, logout } = useAuth();
  const { t } = useLanguage();
  const navigate = useNavigate();

  const [profile, setProfile] = useState<Profile | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [togglingAlerts, setTogglingAlerts] = useState(false);

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [passwordMessage, setPasswordMessage] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletePassword, setDeletePassword] = useState('');
  const [deleteMessage, setDeleteMessage] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!token) return;
    let active = true;
    getMe(token)
      .then((p) => {
        if (active) setProfile(p);
      })
      .catch((err: unknown) => {
        if (active) setLoadError(err instanceof Error ? err.message : t('account.loadFailed'));
      });
    return () => {
      active = false;
    };
  }, [token, t]);

  async function toggleEmailAlerts() {
    if (!token || !profile) return;
    setTogglingAlerts(true);
    try {
      const updated = await updatePreferences(token, !profile.email_alerts_enabled);
      setProfile(updated);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : t('account.loadFailed'));
    } finally {
      setTogglingAlerts(false);
    }
  }

  async function handlePasswordSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setChangingPassword(true);
    setPasswordMessage(null);
    try {
      await changePassword(token, currentPassword, newPassword);
      setPasswordError(false);
      setPasswordMessage(t('account.passwordUpdated'));
      setCurrentPassword('');
      setNewPassword('');
    } catch (err) {
      setPasswordError(true);
      setPasswordMessage(err instanceof Error ? err.message : t('account.loadFailed'));
    } finally {
      setChangingPassword(false);
    }
  }

  async function handleDeleteConfirm() {
    if (!token) return;
    setDeleting(true);
    setDeleteMessage(null);
    try {
      await deleteAccount(token, deletePassword);
      logout();
      navigate('/');
    } catch (err) {
      setDeleteMessage(err instanceof Error ? err.message : t('account.loadFailed'));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <main className="mx-auto flex max-w-feed flex-col gap-6 px-4 py-8">
      <h1 className="font-display text-3xl font-bold text-ink">{t('account.pageTitle')}</h1>

      {loadError && <p role="alert" className="text-xs text-bearish">{loadError}</p>}

      <section className="flex flex-col gap-2 rounded-lg border border-hairline bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-muted">{t('account.profileHeading')}</h2>
        <p className="text-sm text-ink">{profile?.email}</p>
        {profile && (
          <p className="text-xs text-muted">
            {t('account.memberSince', { date: formatMemberSince(profile.created_at) })}
          </p>
        )}
      </section>

      <section className="flex flex-col gap-4 rounded-lg border border-hairline bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-muted">{t('account.preferencesHeading')}</h2>
        <div className="flex items-center justify-between">
          <span className="text-sm text-ink">{t('account.languageLabel')}</span>
          <LanguagePicker />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm text-ink">{t('account.themeLabel')}</span>
          <ThemeToggle />
        </div>
        {profile && (
          <label className="flex cursor-pointer items-start justify-between gap-4">
            <span className="flex flex-col gap-1">
              <span className="text-sm text-ink">{t('account.emailAlertsLabel')}</span>
              <span className="text-xs text-muted">{t('account.emailAlertsHint')}</span>
            </span>
            <input
              type="checkbox"
              checked={profile.email_alerts_enabled}
              disabled={togglingAlerts}
              onChange={toggleEmailAlerts}
              aria-label={t('account.emailAlertsLabel')}
            />
          </label>
        )}
      </section>

      <section className="flex flex-col gap-4 rounded-lg border border-hairline bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-muted">{t('account.watchlistHeading')}</h2>
        <WatchlistSettings />
      </section>

      <section className="flex items-center justify-between rounded-lg border border-hairline bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-muted">{t('account.holdingsHeading')}</h2>
        <Link to="/holdings" className="text-sm text-ink underline">
          {t('account.viewHoldings')}
        </Link>
      </section>

      <section className="flex flex-col gap-4 rounded-lg border border-hairline bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-muted">{t('account.securityHeading')}</h2>
        <form onSubmit={handlePasswordSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-widest text-muted">
              {t('account.currentPasswordLabel')}
            </span>
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="rounded-lg border border-hairline bg-page px-3 py-2 text-ink outline-none focus:border-muted theme-light:border-transparent theme-light:shadow-neu-inset"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-widest text-muted">
              {t('account.newPasswordLabel')}
            </span>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="rounded-lg border border-hairline bg-page px-3 py-2 text-ink outline-none focus:border-muted theme-light:border-transparent theme-light:shadow-neu-inset"
            />
          </label>
          {passwordMessage && (
            <p role="alert" className={`text-xs ${passwordError ? 'text-bearish' : 'text-bullish'}`}>
              {passwordMessage}
            </p>
          )}
          <button
            type="submit"
            disabled={changingPassword}
            className="self-start rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50 theme-light:border-transparent theme-light:bg-accent theme-light:text-page theme-light:shadow-neu"
          >
            {changingPassword ? t('account.updatingPassword') : t('account.updatePassword')}
          </button>
        </form>
      </section>

      <section className="flex flex-col gap-4 rounded-lg border border-bearish/40 bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-bearish">{t('account.dangerZoneHeading')}</h2>
        {!deleteOpen ? (
          <button
            type="button"
            onClick={() => setDeleteOpen(true)}
            className="self-start rounded-lg border border-bearish px-4 py-2 text-xs uppercase tracking-widest text-bearish"
          >
            {t('account.deleteAccount')}
          </button>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-xs text-muted">{t('account.deleteWarning')}</p>
            <label className="flex flex-col gap-1">
              <span className="text-xs uppercase tracking-widest text-muted">
                {t('account.deletePasswordLabel')}
              </span>
              <input
                type="password"
                value={deletePassword}
                onChange={(e) => setDeletePassword(e.target.value)}
                className="rounded-lg border border-hairline bg-page px-3 py-2 text-ink outline-none focus:border-muted theme-light:border-transparent theme-light:shadow-neu-inset"
              />
            </label>
            {deleteMessage && <p role="alert" className="text-xs text-bearish">{deleteMessage}</p>}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={handleDeleteConfirm}
                disabled={deleting}
                className="rounded-lg border border-bearish bg-bearish px-4 py-2 text-xs uppercase tracking-widest text-page disabled:opacity-50"
              >
                {deleting ? t('account.deleting') : t('account.confirmDelete')}
              </button>
              <button
                type="button"
                onClick={() => {
                  setDeleteOpen(false);
                  setDeletePassword('');
                  setDeleteMessage(null);
                }}
                className="rounded-lg border border-hairline px-4 py-2 text-xs uppercase tracking-widest text-ink"
              >
                {t('account.cancel')}
              </button>
            </div>
          </div>
        )}
      </section>

      <button
        type="button"
        onClick={logout}
        className="self-start rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink theme-light:border-transparent theme-light:bg-accent theme-light:text-page theme-light:shadow-neu"
      >
        {t('nav.logout')}
      </button>
    </main>
  );
}
