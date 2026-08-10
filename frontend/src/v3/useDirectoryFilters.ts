/* Thin state hook over directoryFilters.ts -- local useState per app
   convention (no URL params, no context). */
import { useMemo, useState } from 'react';
import type { DirectoryCompany } from './api';
import {
  DEFAULT_DIRECTORY_FILTERS,
  applyDirectoryView,
  indexTierOptions,
  sectorOptions,
  subSectorOptions,
  type DirectoryFilterState,
} from './directoryFilters';

export function useDirectoryFilters(companies: DirectoryCompany[] | null) {
  const [filters, setFilters] = useState<DirectoryFilterState>(DEFAULT_DIRECTORY_FILTERS);

  function patchFilters(patch: Partial<DirectoryFilterState>) {
    setFilters((prev) => {
      const next = { ...prev, ...patch };
      // A sector change invalidates the sub-sector chosen for the old sector;
      // re-selecting the same sector must not clear it.
      if (patch.sector !== undefined && patch.sector !== prev.sector) next.subSector = 'ALL';
      return next;
    });
  }

  const list = useMemo(() => companies ?? [], [companies]);
  const sectors = useMemo(() => sectorOptions(list), [list]);
  const subSectors = useMemo(() => subSectorOptions(list, filters.sector), [list, filters.sector]);
  const indexTiers = useMemo(() => indexTierOptions(list), [list]);
  const filtered = useMemo(() => applyDirectoryView(list, filters), [list, filters]);

  return { filters, patchFilters, sectors, subSectors, indexTiers, filtered };
}
