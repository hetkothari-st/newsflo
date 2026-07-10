import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { getCategories, getCompanies, getWatchlist, putWatchlist, type Company } from '../lib/api';
import { useAuth } from '../lib/auth';

export default function WatchlistSettings({ onSaved }: { onSaved?: () => void }) {
  const { token } = useAuth();
  const [categories, setCategories] = useState<string[]>([]);
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
    Promise.all([getCategories(), getCompanies(), getWatchlist(token)])
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
        setMessage(err instanceof Error ? err.message : 'Failed to load filters.');
      });
    return () => {
      active = false;
    };
  }, [token]);

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
      setMessage('Filters saved.');
      onSaved?.();
    } catch (err) {
      setIsError(true);
      setMessage(err instanceof Error ? err.message : 'Could not save filters.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={handleSave}
      className="flex flex-col gap-5 rounded-lg border border-hairline bg-surface p-5"
      aria-label="Custom filters"
    >
      <div className="flex flex-col gap-2">
        <p className="text-xs uppercase tracking-widest text-muted">Categories</p>
        {categories.length === 0 ? (
          <p className="text-xs text-muted">No categories yet.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {categories.map((category) => (
              <label key={category} className="flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  checked={selectedCategories.has(category)}
                  onChange={() => toggleCategory(category)}
                />
                <span>{category}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-xs uppercase tracking-widest text-muted">Companies</p>
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by name or ticker"
          aria-label="Filter companies"
          className="rounded-lg border border-hairline bg-page px-3 py-2 text-ink outline-none focus:border-muted"
        />
        <div className="flex max-h-64 flex-col gap-2 overflow-y-auto">
          {filteredCompanies.map((company) => (
            <label key={company.id} className="flex items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={selectedCompanyIds.has(company.id)}
                onChange={() => toggleCompany(company.id)}
              />
              <span>{company.name}</span>
              <span className="text-xs text-muted">{company.ticker}</span>
            </label>
          ))}
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
        className="self-start rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50"
      >
        {saving ? 'Saving…' : 'Save'}
      </button>
    </form>
  );
}
