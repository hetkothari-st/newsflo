import { useState } from 'react';
import type { Alert, AlertCompany } from '../lib/api';
import type { TranslationKey } from '../lib/i18n';
import { useLanguage } from '../lib/language';
import CompanyChip from './CompanyChip';
import SentimentBar from '../features/visualize/SentimentBar';
import CompanyTree from '../features/visualize/CompanyTree';
import {
  groupByTier,
  groupByImpact,
  groupBySector,
  type CompanyGroup,
  type GroupMode,
} from '../features/visualize/transforms';

type Tab = 'predicted' | 'my_demat';
type ViewMode = 'list' | 'chart';

const GROUP_MODES: GroupMode[] = ['tier', 'impact', 'sector'];
const GROUP_LABEL_KEY: Record<GroupMode, TranslationKey> = {
  tier: 'companies.groupTier',
  impact: 'companies.groupImpact',
  sector: 'companies.groupSector',
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
  const { t } = useLanguage();
  const [tab, setTab] = useState<Tab>('predicted');
  const [groupMode, setGroupMode] = useState<GroupMode>('tier');
  const [viewMode, setViewMode] = useState<ViewMode>('list');

  const visible = tab === 'predicted' ? alert.companies : alert.companies.filter((c) => c.in_my_holdings);
  const grouped = groupCompanies(groupMode, visible);

  const tabClass = (active: boolean) =>
    `pb-1 text-xs uppercase tracking-widest border-b-2 ${
      active ? 'border-ink text-ink' : 'border-transparent text-muted'
    }`;

  const emptyCopy =
    tab === 'my_demat'
      ? isAuthenticated
        ? t('companies.emptyMyDematAuthed')
        : t('companies.emptyMyDematAnon')
      : t('companies.emptyPredicted');

  return (
    <div className="flex flex-col gap-4">
      <div className="no-scrollbar flex flex-nowrap items-center justify-between gap-x-4 overflow-x-auto">
        <div className="flex shrink-0 gap-4">
          <button type="button" onClick={() => setTab('predicted')} className={tabClass(tab === 'predicted')}>
            {t('companies.predicted')}
          </button>
          <button type="button" onClick={() => setTab('my_demat')} className={tabClass(tab === 'my_demat')}>
            {t('companies.myPortfolio')}
          </button>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs uppercase tracking-widest text-muted">
            {t('companies.group')}
            <select
              value={groupMode}
              onChange={(e) => setGroupMode(e.target.value as GroupMode)}
              className="rounded-md border border-hairline bg-surface px-1.5 py-0.5 text-xs text-ink theme-light:border-transparent theme-light:shadow-neu-sm"
            >
              {GROUP_MODES.map((mode) => (
                <option key={mode} value={mode}>
                  {t(GROUP_LABEL_KEY[mode])}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <SentimentBar companies={visible} />
      {grouped.length === 0 ? (
        <p className="text-xs text-muted">{emptyCopy}</p>
      ) : (
        <>
          <div className="flex gap-1 self-start rounded-md border border-hairline bg-surface p-0.5 theme-light:border-transparent theme-light:shadow-neu-sm">
            {(['list', 'chart'] as ViewMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setViewMode(mode)}
                className={`rounded px-2 py-0.5 text-[11px] uppercase tracking-widest ${
                  viewMode === mode ? 'bg-page text-ink' : 'text-muted'
                }`}
              >
                {mode === 'list' ? t('companies.list') : t('companies.chart')}
              </button>
            ))}
          </div>
          {viewMode === 'chart' ? (
            <CompanyTree articleTitle={alert.article.title} groups={grouped} groupMode={groupMode} />
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
        </>
      )}
    </div>
  );
}
