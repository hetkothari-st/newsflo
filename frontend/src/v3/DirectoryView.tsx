/* Directory (spec v2 §10 milestone 1): browse every tracked stock.
   Search, cap-tier/sector/sub-sector/index-tier filters, PE/PB/ROE ranges,
   sort -- all client-side over one fetch (logic in directoryFilters.ts). */
import { useEffect, useState } from 'react';
import { getDirectory, type DirectoryCompany } from './api';
import DirectoryFilterBar from './DirectoryFilterBar';
import DirectoryRow from './DirectoryRow';
import { capClass } from './format';
import { useDirectoryFilters } from './useDirectoryFilters';
import { useAuth } from '../lib/auth';

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
  const { filters, patchFilters, sectors, subSectors, indexTiers, filtered } =
    useDirectoryFilters(companies);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    getDirectory(token)
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

  return (
    <div className={`view ${active ? 'on' : ''}`}>
      <div className="pagehd">
        <h2>Directory</h2>
        <p>Every tracked stock. Search, filter and sort.</p>
      </div>
      <DirectoryFilterBar
        filters={filters}
        onChange={patchFilters}
        sectors={sectors}
        subSectors={subSectors}
        indexTiers={indexTiers}
      />
      <div className="legend">
        {(['LARGE', 'MID', 'SMALL', 'MICRO'] as const).map((tier) => (
          <span key={tier}>
            <span className={`tag ${capClass(tier)}`}>{tier}</span>
          </span>
        ))}
      </div>
      {error !== null && <p className="empty">{error}</p>}
      {companies !== null && filtered.length === 0 && (
        <p className="empty">No companies match these filters.</p>
      )}
      {filtered.map((company) => (
        <DirectoryRow key={company.ticker} company={company} onOpenDeepDive={onOpenDeepDive} />
      ))}
    </div>
  );
}
