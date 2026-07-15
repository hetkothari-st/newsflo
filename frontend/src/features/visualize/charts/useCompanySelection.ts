import { useState } from 'react';
import type { AlertCompany } from '../../../lib/api';

// Shared tap-to-expand selection logic for the six charts-page chart
// components (SectorTree, TierRows, ImpactBar, SplitTree, ConfidenceTree,
// TimelineTree). Each chart renders a grid/list of company chips/bars/rows
// and expands a single ReasoningPanel below itself for whichever company
// was last tapped; tapping the same company again collapses it.
export function useCompanySelection(companies: AlertCompany[]) {
  const [selectedId, setSelectedId] = useState<number | null>(null);

  function toggle(companyId: number) {
    setSelectedId((id) => (id === companyId ? null : companyId));
  }

  const selected = selectedId !== null ? companies.find((c) => c.company_id === selectedId) ?? null : null;

  return { selectedId, toggle, selected };
}
