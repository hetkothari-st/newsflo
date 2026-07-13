import { useState } from 'react';
import type { Alert, AlertCompany } from '../lib/api';
import CompanyChip from './CompanyChip';
import { groupByTier, groupByImpact, groupBySector, type CompanyGroup } from '../features/visualize/transforms';

type Tab = 'predicted' | 'my_demat';
type GroupMode = 'tier' | 'impact' | 'sector';

const GROUP_MODES: GroupMode[] = ['tier', 'impact', 'sector'];
const GROUP_LABEL: Record<GroupMode, string> = {
  tier: 'Tier',
  impact: 'Impact',
  sector: 'Sector',
};

function groupCompanies(mode: GroupMode, companies: AlertCompany[]): CompanyGroup[] {
  if (mode === 'impact') return groupByImpact(companies);
  if (mode === 'sector') return groupBySector(companies);
  return groupByTier(companies);
}

function headerClass(mode: GroupMode, group: CompanyGroup): string {
  if (mode === 'impact') return group.key === 'bullish' ? 'text-bullish' : 'text-bearish';
  return 'text-muted';
}

export default function AlertCompanies({
  alert,
  isAuthenticated,
}: {
  alert: Alert;
  isAuthenticated: boolean;
}) {
  const [tab, setTab] = useState<Tab>('predicted');
  const [groupMode, setGroupMode] = useState<GroupMode>('tier');

  const visible = tab === 'predicted' ? alert.companies : alert.companies.filter((c) => c.in_my_holdings);
  const grouped = groupCompanies(groupMode, visible);

  const tabClass = (active: boolean) =>
    `pb-1 text-xs uppercase tracking-widest border-b-2 ${
      active ? 'border-ink text-ink' : 'border-transparent text-muted'
    }`;

  const emptyCopy =
    tab === 'my_demat'
      ? isAuthenticated
        ? 'None of your holdings are affected by this story.'
        : 'Log in to see holdings-matched alerts.'
      : 'No affected companies for this story.';

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <div className="flex gap-4">
          <button type="button" onClick={() => setTab('predicted')} className={tabClass(tab === 'predicted')}>
            Predicted
          </button>
          <button type="button" onClick={() => setTab('my_demat')} className={tabClass(tab === 'my_demat')}>
            My Portfolio
          </button>
        </div>
        <label className="flex items-center gap-1.5 text-xs uppercase tracking-widest text-muted">
          Group
          <select
            value={groupMode}
            onChange={(e) => setGroupMode(e.target.value as GroupMode)}
            className="rounded-md border border-hairline bg-surface px-1.5 py-0.5 text-xs text-ink theme-light:border-transparent theme-light:shadow-neu-sm"
          >
            {GROUP_MODES.map((mode) => (
              <option key={mode} value={mode}>
                {GROUP_LABEL[mode]}
              </option>
            ))}
          </select>
        </label>
      </div>
      {visible.length === 0 ? (
        <p className="text-xs text-muted">{emptyCopy}</p>
      ) : (
        grouped.map((group) => (
          <div key={group.key} className="flex flex-col gap-2">
            <p className={`flex items-center gap-1.5 text-xs uppercase tracking-widest ${headerClass(groupMode, group)}`}>
              {group.color && (
                <span aria-hidden="true" className="h-2 w-2 rounded-full" style={{ backgroundColor: group.color }} />
              )}
              {groupMode === 'tier' ? group.label : `${group.label} · ${group.companies.length}`}
            </p>
            <div className="grid grid-cols-1 items-start gap-2 sm:grid-cols-2">
              {group.companies.map((company) => (
                <div
                  key={company.company_id}
                  className={groupMode !== 'tier' && company.basis === 'sector_inference' ? 'opacity-70' : undefined}
                >
                  <CompanyChip company={company} />
                </div>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
