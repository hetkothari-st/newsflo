/* Presentational filter bar for the Directory view -- all state lives in
   useDirectoryFilters; this only renders controls and reports patches. */
import { useState } from 'react';
import type { CapTier } from './api';
import { subSectorLabel } from '../features/visualize/subSectorLabels';
import { sectorLabel } from '../features/visualize/transforms';
import type { DirectoryFilterState, DirectorySort } from './directoryFilters';

const CAP_OPTIONS: Array<CapTier | 'ALL'> = ['ALL', 'LARGE', 'MID', 'SMALL', 'MICRO'];

const INDEX_TIER_LABELS: Record<string, string> = {
  NIFTY50: 'Nifty 50',
  NIFTY100: 'Nifty 100',
  NIFTY500: 'Nifty 500',
  OTHER: 'Other',
};

const SORT_OPTIONS: Array<{ value: DirectorySort; label: string }> = [
  { value: 'ticker', label: 'Ticker A–Z' },
  { value: 'name', label: 'Name' },
  { value: 'market_cap_desc', label: 'Market cap (high→low)' },
];

export default function DirectoryFilterBar({
  filters,
  onChange,
  sectors,
  subSectors,
  indexTiers,
}: {
  filters: DirectoryFilterState;
  onChange: (patch: Partial<DirectoryFilterState>) => void;
  sectors: string[];
  subSectors: string[];
  indexTiers: string[];
}) {
  const [advancedOpen, setAdvancedOpen] = useState(false);

  return (
    <>
      <div className="dirfilter">
        <input
          type="search"
          aria-label="Search directory"
          placeholder="Search name or ticker"
          value={filters.search}
          onChange={(event) => onChange({ search: event.target.value })}
        />
        <select
          aria-label="Cap tier filter"
          value={filters.capTier}
          onChange={(event) => onChange({ capTier: event.target.value as CapTier | 'ALL' })}
        >
          {CAP_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option === 'ALL' ? 'All caps' : option}
            </option>
          ))}
        </select>
        <select
          aria-label="Sector filter"
          value={filters.sector}
          onChange={(event) => onChange({ sector: event.target.value })}
        >
          {sectors.map((sector) => (
            <option key={sector} value={sector}>
              {sector === 'ALL' ? 'All sectors' : sectorLabel(sector)}
            </option>
          ))}
        </select>
        {subSectors.length > 0 && (
          <select
            aria-label="Sub-sector filter"
            value={filters.subSector}
            onChange={(event) => onChange({ subSector: event.target.value })}
          >
            {subSectors.map((sub) => (
              <option key={sub} value={sub}>
                {sub === 'ALL' ? 'All sub-sectors' : subSectorLabel(sub)}
              </option>
            ))}
          </select>
        )}
        <select
          aria-label="Index tier filter"
          value={filters.indexTier}
          onChange={(event) => onChange({ indexTier: event.target.value })}
        >
          {indexTiers.map((tier) => (
            <option key={tier} value={tier}>
              {tier === 'ALL' ? 'All indices' : (INDEX_TIER_LABELS[tier] ?? tier)}
            </option>
          ))}
        </select>
        <select
          aria-label="Sort directory"
          value={filters.sort}
          onChange={(event) => onChange({ sort: event.target.value as DirectorySort })}
        >
          {SORT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={`adv-toggle ${advancedOpen ? 'on' : ''}`}
          aria-expanded={advancedOpen}
          onClick={() => setAdvancedOpen((open) => !open)}
        >
          Advanced {advancedOpen ? '▴' : '▾'}
        </button>
      </div>
      {advancedOpen && (
        <div className="diradv">
          {(
            [
              { label: 'PE', minKey: 'peMin', maxKey: 'peMax' },
              { label: 'PB', minKey: 'pbMin', maxKey: 'pbMax' },
              { label: 'ROE %', minKey: 'roeMin', maxKey: 'roeMax' },
            ] as const
          ).map(({ label, minKey, maxKey }) => (
            <div className="diradv-field" key={label}>
              <span className="lab">{label}</span>
              <div className="range">
                <input
                  type="number"
                  inputMode="decimal"
                  aria-label={`${label} min`}
                  placeholder="min"
                  value={filters[minKey]}
                  onChange={(event) => onChange({ [minKey]: event.target.value })}
                />
                <input
                  type="number"
                  inputMode="decimal"
                  aria-label={`${label} max`}
                  placeholder="max"
                  value={filters[maxKey]}
                  onChange={(event) => onChange({ [maxKey]: event.target.value })}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
