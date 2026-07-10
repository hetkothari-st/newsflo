import type { AlertCompany } from '../../lib/api';
import type { TreeNodeData } from './tree';
import { sectorColor } from './colors';

const BULLISH_COLOR = '#34C759';
const BEARISH_COLOR = '#FF453A';

function leafNode(company: AlertCompany): TreeNodeData {
  return {
    id: `company-${company.company_id}`,
    label: company.name,
    kind: 'leaf',
    leaf: {
      companyId: company.company_id,
      ticker: company.ticker,
      name: company.name,
      direction: company.direction,
      rationale: company.rationale,
    },
    children: [],
  };
}

export function buildImpactTree(articleTitle: string, companies: AlertCompany[]): TreeNodeData {
  const bullish = companies.filter((c) => c.direction === 'bullish');
  const bearish = companies.filter((c) => c.direction === 'bearish');

  const branches: TreeNodeData[] = [];
  if (bullish.length > 0) {
    branches.push({ id: 'branch-bullish', label: 'Bullish', kind: 'branch', color: BULLISH_COLOR, children: bullish.map(leafNode) });
  }
  if (bearish.length > 0) {
    branches.push({ id: 'branch-bearish', label: 'Bearish', kind: 'branch', color: BEARISH_COLOR, children: bearish.map(leafNode) });
  }

  return { id: 'root', label: articleTitle, kind: 'root', children: branches };
}

export function buildSectorTree(articleTitle: string, companies: AlertCompany[]): TreeNodeData {
  const bySector = new Map<string, AlertCompany[]>();
  for (const company of companies) {
    const sector = company.sector && company.sector.trim().length > 0 ? company.sector : 'Other';
    const group = bySector.get(sector) ?? [];
    group.push(company);
    bySector.set(sector, group);
  }

  const branches: TreeNodeData[] = [...bySector.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([sector, group]) => ({
      id: `branch-${sector}`, label: sector, kind: 'branch', color: sectorColor(sector), children: group.map(leafNode),
    }));

  return { id: 'root', label: articleTitle, kind: 'root', children: branches };
}
