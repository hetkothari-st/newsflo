import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { capTierColorClass } from '../lib/feedV2Format';
import { getDirectory, type CapTier, type DirectoryCompany } from '../lib/feedV2Api';
import { useAuth } from '../lib/auth';

const CAP_TIERS: CapTier[] = ['LARGE', 'MID', 'SMALL'];

export default function DirectoryPage() {
  const { token } = useAuth();
  const [capTier, setCapTier] = useState<CapTier | ''>('');
  const [sector, setSector] = useState('');
  const [companies, setCompanies] = useState<DirectoryCompany[]>([]);

  useEffect(() => {
    let active = true;
    const filters = {
      ...(capTier ? { capTier } : {}),
      ...(sector ? { sector } : {}),
    };
    getDirectory(filters, token)
      .then((data) => {
        if (active) setCompanies(data);
      })
      .catch(() => {
        if (active) setCompanies([]);
      });
    return () => {
      active = false;
    };
  }, [capTier, sector, token]);

  const sectors = Array.from(new Set(companies.map((c) => c.sector))).sort();

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 py-8">
      <div className="rounded-lg bg-surface p-5">
        <div className="flex gap-4">
          <label className="flex flex-col gap-1 font-sans text-xs text-muted">
            Cap tier
            <select
              aria-label="Cap tier"
              value={capTier}
              onChange={(e) => setCapTier(e.target.value as CapTier | '')}
              className="rounded-md border border-hairline bg-page px-2 py-1 font-sans text-sm text-ink"
            >
              <option value="">All</option>
              {CAP_TIERS.map((tier) => (
                <option key={tier} value={tier}>
                  {tier}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 font-sans text-xs text-muted">
            Sector
            <select
              aria-label="Sector"
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              className="rounded-md border border-hairline bg-page px-2 py-1 font-sans text-sm text-ink"
            >
              <option value="">All</option>
              {sectors.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="rounded-lg bg-surface p-5">
        <div className="flex flex-col divide-y divide-hairline">
          {companies.map((company) => (
            <Link
              key={company.ticker}
              to={`/feed-v2/stock/${company.ticker}`}
              className="flex items-center gap-3 py-2"
            >
              <span className="flex-1 font-sans text-sm text-ink">{company.name}</span>
              <span className="font-data text-[11px] text-muted">{company.ticker}</span>
              <span className="font-sans text-xs uppercase tracking-widest text-muted">{company.sector}</span>
              <span
                className={`rounded-full px-2 py-0.5 font-sans text-[10px] uppercase tracking-widest ${capTierColorClass(company.cap_tier)}`}
              >
                {company.cap_tier}
              </span>
            </Link>
          ))}
        </div>
      </div>
    </main>
  );
}
