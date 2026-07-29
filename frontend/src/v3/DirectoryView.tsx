/* Directory (spec v2 §10 milestone 1): browse every tracked stock,
   filter by cap tier and sector, cap-tag legend in the header. */
import { useEffect, useMemo, useState } from 'react';
import { getDirectory, type CapTier, type DirectoryCompany } from './api';
import { capClass } from './format';
import { useAuth } from '../lib/auth';

const CAP_OPTIONS: Array<CapTier | 'ALL'> = ['ALL', 'LARGE', 'MID', 'SMALL', 'MICRO'];

export default function DirectoryView({
  active,
  onOpenDeepDive,
}: {
  active: boolean;
  onOpenDeepDive: (ticker: string) => void;
}) {
  const { token } = useAuth();
  const [companies, setCompanies] = useState<DirectoryCompany[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [capFilter, setCapFilter] = useState<CapTier | 'ALL'>('ALL');
  const [sectorFilter, setSectorFilter] = useState<string>('ALL');

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    getDirectory({}, token)
      .then((result) => {
        if (!cancelled) setCompanies(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [active, token]);

  const sectors = useMemo(() => {
    const unique = new Set((companies ?? []).map((company) => company.sector));
    return ['ALL', ...Array.from(unique).sort()];
  }, [companies]);

  const filtered = (companies ?? []).filter(
    (company) =>
      (capFilter === 'ALL' || company.cap_tier === capFilter) &&
      (sectorFilter === 'ALL' || company.sector === sectorFilter),
  );

  return (
    <div className={`view ${active ? 'on' : ''}`}>
      <div className="pagehd">
        <h2>Directory</h2>
        <p>Every tracked stock. Filter by cap tier and sector.</p>
      </div>
      <div className="dirfilter">
        <select
          aria-label="Cap tier filter"
          value={capFilter}
          onChange={(event) => setCapFilter(event.target.value as CapTier | 'ALL')}
        >
          {CAP_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option === 'ALL' ? 'All caps' : option}
            </option>
          ))}
        </select>
        <select
          aria-label="Sector filter"
          value={sectorFilter}
          onChange={(event) => setSectorFilter(event.target.value)}
        >
          {sectors.map((sector) => (
            <option key={sector} value={sector}>
              {sector === 'ALL' ? 'All sectors' : sector.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
      </div>
      <div className="legend">
        <span>
          <span className="tag cap-L">LARGE</span>
        </span>
        <span>
          <span className="tag cap-M">MID</span>
        </span>
        <span>
          <span className="tag cap-S">SMALL</span>
        </span>
        <span>
          <span className="tag cap-U">MICRO</span>
        </span>
      </div>
      {error !== null && <p className="empty">{error}</p>}
      {companies !== null && filtered.length === 0 && (
        <p className="empty">No companies match these filters.</p>
      )}
      {filtered.map((company) => (
        <div className="direntry" key={company.ticker} onClick={() => onOpenDeepDive(company.ticker)}>
          <div>
            <div className="de-name">{company.name}</div>
            <div className="de-tk">
              {company.ticker} · {company.sector.replace(/_/g, ' ')}
            </div>
          </div>
          <span className={`de-cap tag ${capClass(company.cap_tier)}`}>{company.cap_tier ?? '—'}</span>
        </div>
      ))}
    </div>
  );
}
