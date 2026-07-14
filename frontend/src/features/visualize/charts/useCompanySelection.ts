import { useState } from 'react';
import type { AlertCompany } from '../../../lib/api';

// Shared tap-to-expand selection logic for the four charts-page chart
// components (SectorTreemap, TierRows, ImpactBar, SplitDonut). Each chart
// renders a grid/list of company chips/bars/rows and expands a single
// ReasoningPanel below itself for whichever company was last tapped;
// tapping the same company again collapses it.
export function useCompanySelection(companies: AlertCompany[]) {
  const [selectedId, setSelectedId] = useState<number | null>(null);

  function toggle(companyId: number) {
    setSelectedId((id) => (id === companyId ? null : companyId));
  }

  const selected = selectedId !== null ? companies.find((c) => c.company_id === selectedId) ?? null : null;

  return { selectedId, toggle, selected };
}
