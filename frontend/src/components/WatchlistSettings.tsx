import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { getCategories, getCompanies, getWatchlist, putWatchlist, type CategoryOption, type Company } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
import CategorySwatch from './CategorySwatch';

// Full static class strings (not built by interpolation) so Tailwind's content
// scanner keeps them. Selected chips tint with the same accent used for the
// category's swatch dot everywhere else in the app.
const CHIP_ACCENT: Record<string, string> = {
  oil_energy: 'border-swatch-oil_energy bg-swatch-oil_energy/10',
  banking: 'border-swatch-banking bg-swatch-banking/10',
  auto_ev: 'border-swatch-auto_ev bg-swatch-auto_ev/10',
  geopolitics: 'border-swatch-geopolitics bg-swatch-geopolitics/10',
};
const CHIP_ACCENT_FALLBACK = 'border-swatch-other bg-swatch-other/10';

export default function WatchlistSettings({ onSaved }: { onSaved?: () => void }) {
  const { token } = useAuth();
  const { language, t } = useLanguage();
  const [categories, setCategories] = useState<CategoryOption[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(new Set());
  const [selectedCompanyIds, setSelectedCompanyIds] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!token) return;
    let active = true;
    Promise.all([getCategories(language), getCompanies(), getWatchlist(token)])
      .then(([cats, comps, watchlist]) => {
        if (!active) return;
        setCategories(cats);
        setCompanies(comps);
        setSelectedCategories(new Set(watchlist.categories));
        setSelectedCompanyIds(new Set(watchlist.companies.map((c) => c.company_id)));
      })
      .catch((err: unknown) => {
        if (!active) return;
        setIsError(true);
        setMessage(err instanceof Error ? err.message : t('watchlist.loadFailed'));
      });
    return () => {
      active = false;
    };
  }, [token, language, t]);

  const filteredCompanies = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return companies;
    return companies.filter(
      (c) => c.name.toLowerCase().includes(q) || c.ticker.toLowerCase().includes(q),
    );
  }, [companies, filter]);

  function toggleCategory(category: string) {
    setSelectedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  }

  function toggleCompany(companyId: number) {
    setSelectedCompanyIds((prev) => {
      const next = new Set(prev);
      if (next.has(companyId)) next.delete(companyId);
      else next.add(companyId);
      return next;
    });
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setSaving(true);
    setMessage(null);
    try {
      await putWatchlist(token, [...selectedCategories], [...selectedCompanyIds]);
      setIsError(false);
      setMessage(t('watchlist.saved'));
      onSaved?.();
    } catch (err) {
      setIsError(true);
      setMessage(err instanceof Error ? err.message : t('watchlist.saveFailed'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={handleSave}
      className="flex flex-col gap-6 rounded-lg border border-hairline bg-surface p-6"
      aria-label={t('watchlist.formAria')}
    >
      <div className="flex flex-col gap-3">
        <p className="text-xs uppercase tracking-widest text-muted">{t('watchlist.categoriesLabel')}</p>
        {categories.length === 0 ? (
          <p className="text-xs text-muted">{t('watchlist.noCategories')}</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {categories.map(({ category, label }) => {
              const selected = selectedCategories.has(category);
              const accent = selected ? (CHIP_ACCENT[category] ?? CHIP_ACCENT_FALLBACK) : 'border-hairline bg-page hover:border-muted theme-light:shadow-neu-sm';
              return (
                <label
                  key={category}
                  className={`inline-flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 motion-safe:transition-colors ${accent}`}
                >
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={selected}
                    onChange={() => toggleCategory(category)}
                    aria-label={label}
                  />
                  <CategorySwatch category={category} label={language === 'en' ? undefined : label} active={selected} />
                </label>
              );
            })}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-3">
        <p className="text-xs uppercase tracking-widest text-muted">{t('watchlist.companiesLabel')}</p>
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={t('watchlist.filterPlaceholder')}
          aria-label={t('watchlist.filterAria')}
          className="rounded-lg border border-hairline bg-page px-3 py-2 text-ink outline-none focus:border-muted theme-light:border-transparent theme-light:shadow-neu-inset"
        />
        <div className="flex max-h-64 flex-col gap-2 overflow-y-auto pr-1">
          {filteredCompanies.map((company) => {
            const selected = selectedCompanyIds.has(company.id);
            return (
              <label
                key={company.id}
                className={`flex cursor-pointer items-center justify-between rounded-lg border px-3 py-2 motion-safe:transition-colors ${
                  selected
                    ? 'border-accent bg-hairline/40 theme-light:bg-accent/10'
                    : 'border-hairline bg-page hover:border-muted theme-light:shadow-neu-sm'
                }`}
              >
                <span className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={selected}
                    onChange={() => toggleCompany(company.id)}
                  />
                  <span
                    aria-hidden="true"
                    className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border text-[10px] leading-none ${
                      selected ? 'border-accent bg-accent text-page' : 'border-hairline text-transparent'
                    }`}
                  >
                    ✓
                  </span>
                  <span className="text-sm text-ink">{company.name}</span>
                </span>
                <span className="text-xs text-muted">{company.ticker}</span>
              </label>
            );
          })}
        </div>
      </div>

      {message && (
        <p role="alert" className={`text-xs ${isError ? 'text-bearish' : 'text-bullish'}`}>
          {message}
        </p>
      )}
      <button
        type="submit"
        disabled={saving}
        className="self-start rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50 theme-light:border-transparent theme-light:bg-accent theme-light:text-page theme-light:shadow-neu"
      >
        {saving ? t('watchlist.saving') : t('watchlist.save')}
      </button>
    </form>
  );
}
