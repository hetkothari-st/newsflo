import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  getCompanyHistory,
  getCompanyPrices,
  getCompanyProfile,
  type CompanyHistoryPage,
  type CompanyProfile,
  type PricePeriod,
  type PriceSeries,
} from '../lib/api';
import type { TranslationKey } from '../lib/i18n';
import { useLanguage } from '../lib/language';
import { splitRationaleIntoPoints } from '../lib/reasoning';
import CompanyAvatar from '../components/CompanyAvatar';
import DirectionArrow from '../components/DirectionArrow';
import MentionRow from '../components/MentionRow';
import PriceChart from '../features/visualize/PriceChart';

const PERIODS: PricePeriod[] = ['1mo', '3mo', '6mo', '1y'];
const PERIOD_LABEL_KEY: Record<PricePeriod, TranslationKey> = {
  '1mo': 'company.period1mo',
  '3mo': 'company.period3mo',
  '6mo': 'company.period6mo',
  '1y': 'company.period1y',
};

export default function CompanyPage() {
  const { id } = useParams<{ id: string }>();
  const companyId = Number(id);
  const { t, language } = useLanguage();

  // undefined = still loading, null = confirmed not found -- kept distinct so
  // the not-found message never flashes before the first fetch resolves.
  const [profile, setProfile] = useState<CompanyProfile | null | undefined>(undefined);
  const [profileError, setProfileError] = useState(false);
  const [history, setHistory] = useState<CompanyHistoryPage | null>(null);
  const [historyError, setHistoryError] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [prices, setPrices] = useState<PriceSeries | null>(null);
  const [pricesError, setPricesError] = useState(false);
  const [period, setPeriod] = useState<PricePeriod>('6mo');

  useEffect(() => {
    let active = true;
    setProfile(undefined);
    setProfileError(false);
    getCompanyProfile(companyId, language)
      .then((p) => {
        if (active) setProfile(p);
      })
      .catch(() => {
        if (active) setProfileError(true);
      });
    return () => {
      active = false;
    };
  }, [companyId, language]);

  useEffect(() => {
    let active = true;
    setHistory(null);
    setHistoryError(false);
    getCompanyHistory(companyId)
      .then((page) => {
        if (active) setHistory(page);
      })
      .catch(() => {
        if (active) setHistoryError(true);
      });
    return () => {
      active = false;
    };
  }, [companyId]);

  useEffect(() => {
    let active = true;
    setPrices(null);
    setPricesError(false);
    getCompanyPrices(companyId, period)
      .then((series) => {
        if (active) setPrices(series);
      })
      .catch(() => {
        if (active) setPricesError(true);
      });
    return () => {
      active = false;
    };
  }, [companyId, period]);

  async function loadMore() {
    if (!history || !history.has_more || historyLoading) return;
    setHistoryLoading(true);
    try {
      const lastCreatedAt = history.mentions[history.mentions.length - 1].created_at;
      const next = await getCompanyHistory(companyId, lastCreatedAt);
      setHistory({ mentions: [...history.mentions, ...next.mentions], has_more: next.has_more });
    } catch {
      setHistoryError(true);
    } finally {
      setHistoryLoading(false);
    }
  }

  if (profile === undefined && !profileError) return null;

  if (profileError || !profile) {
    return (
      <main className="mx-auto max-w-feed px-4 py-8">
        <p role="alert" className="text-sm text-muted">
          {t(profileError ? 'company.loadFailed' : 'company.notFound')}
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex max-w-feed flex-col gap-6 px-4 py-8">
      <div className="flex items-center gap-3">
        <CompanyAvatar ticker={profile.ticker} size="lg" />
        <div>
          <h1 className="font-display text-2xl font-bold text-ink">{profile.name}</h1>
          <p className="text-xs uppercase tracking-widest text-muted">
            {profile.ticker} · {profile.sector}
          </p>
        </div>
      </div>

      <section className="flex flex-col gap-3 rounded-lg border border-hairline bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-muted">{t('company.chartHeading')}</h2>
        <div className="flex gap-1 self-start rounded-md border border-hairline bg-page p-0.5">
          {PERIODS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPeriod(p)}
              className={`rounded px-2 py-0.5 text-[11px] uppercase tracking-widest ${
                period === p ? 'bg-surface text-ink' : 'text-muted'
              }`}
            >
              {t(PERIOD_LABEL_KEY[p])}
            </button>
          ))}
        </div>
        {pricesError ? (
          <p className="text-xs text-muted">{t('company.chartLoadFailed')}</p>
        ) : (
          <PriceChart points={prices?.points ?? []} unavailableLabel={t('company.chartUnavailable')} />
        )}
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-hairline bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-muted">{t('company.latestSignalHeading')}</h2>
        {profile.latest_alert ? (
          <>
            <p className="flex items-center gap-1.5 text-sm text-ink">
              <DirectionArrow direction={profile.latest_alert.direction} />
              {profile.latest_alert.category_label}
            </p>
            <ul className="space-y-1.5 text-sm text-ink">
              {(profile.latest_alert.key_points.length > 0
                ? profile.latest_alert.key_points
                : splitRationaleIntoPoints(profile.latest_alert.rationale)
              ).map((point, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-muted" aria-hidden="true">•</span>
                  <span>{point}</span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-xs text-muted">{t('company.noAlertsYet')}</p>
        )}
      </section>

      <section className="flex flex-col gap-2 rounded-lg border border-hairline bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-muted">{t('company.trackRecordHeading')}</h2>
        {profile.track_record ? (
          <ul className="space-y-1 text-sm text-ink">
            {Object.entries(profile.track_record).map(([days, stats]) => (
              <li key={days}>
                {t('company.winRateLabel', {
                  days,
                  rate: Math.round(stats.win_rate * 100),
                  count: stats.sample_size,
                })}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted">{t('company.trackRecordInsufficient')}</p>
        )}
      </section>

      <section className="flex flex-col gap-3 rounded-lg border border-hairline bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-muted">{t('company.historyHeading')}</h2>
        {historyError && <p role="alert" className="text-xs text-muted">{t('company.historyLoadFailed')}</p>}
        {history?.mentions.length === 0 && <p className="text-xs text-muted">{t('company.noHistory')}</p>}
        <ul className="space-y-2">
          {history?.mentions.map((mention) => (
            <MentionRow key={mention.alert_id} mention={mention} />
          ))}
        </ul>
        {history?.has_more && (
          <button
            type="button"
            onClick={loadMore}
            disabled={historyLoading}
            className="self-start text-xs uppercase tracking-widest text-ink underline disabled:opacity-50"
          >
            {t('company.loadMore')}
          </button>
        )}
      </section>
    </main>
  );
}
