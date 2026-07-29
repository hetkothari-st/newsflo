import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Alert, AlertCompany } from '../lib/api';
// TranslationKey only typed the commented-out GROUP_LABEL_KEY below.
// import type { TranslationKey } from '../lib/i18n';
import { useLanguage } from '../lib/language';
import CollapsibleInsightRow from './CollapsibleInsightRow';
import SentimentBar from '../features/visualize/SentimentBar';
import {
  groupByTier,
  groupByImpact,
  groupBySector,
  groupByImpactLevel,
  type CompanyGroup,
  type GroupMode,
} from '../features/visualize/transforms';

type Tab = 'predicted' | 'my_demat';

// Only referenced by the group-by selector, which is commented out below --
// commented out alongside it rather than removed.
// const GROUP_MODES: GroupMode[] = ['tier', 'impact', 'sector'];
// const GROUP_LABEL_KEY: Record<GroupMode, TranslationKey> = {
//   tier: 'companies.groupTier',
//   impact: 'companies.groupImpact',
//   sector: 'companies.groupSector',
// };

function groupCompanies(mode: GroupMode, companies: AlertCompany[]): CompanyGroup[] {
  if (mode === 'impact') return groupByImpact(companies);
  if (mode === 'sector') return groupBySector(companies);
  if (mode === 'impact_level') return groupByImpactLevel(companies);
  return groupByTier(companies);
}

function headerClass(mode: GroupMode, group: CompanyGroup): string {
  if (mode === 'impact') return group.key === 'bullish' ? 'text-bullish' : 'text-bearish';
  return 'text-muted';
}

// Direct Impact starts open (the main reason someone opened this alert);
// Ripple L1/L2 start collapsed -- one row of headers to scan before opting
// into the deeper cascade levels, rather than 16 companies dumped at once.
const DEFAULT_OPEN_IMPACT_LEVELS: Record<string, boolean> = { direct: true };

export default function AlertCompanies({
  alert,
  isAuthenticated,
}: {
  alert: Alert;
  isAuthenticated: boolean;
}) {
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('predicted');
  // setGroupMode is unused while the group-by selector below is commented
  // out -- re-add it to this destructure when the selector comes back.
  const [groupMode] = useState<GroupMode>('impact_level');
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(DEFAULT_OPEN_IMPACT_LEVELS);
  const toggleGroup = (key: string) =>
    setOpenGroups((prev) => ({ ...prev, [key]: !(prev[key] ?? false) }));

  const visible = tab === 'predicted' ? alert.companies : alert.companies.filter((c) => c.in_my_holdings);
  const grouped = groupCompanies(groupMode, visible);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'ArrowRight' && visible.length > 0) {
        const activeElement = document.activeElement as HTMLElement;
        const isEditingControl =
          activeElement?.tagName === 'INPUT' ||
          activeElement?.tagName === 'TEXTAREA' ||
          activeElement?.tagName === 'SELECT' ||
          activeElement?.isContentEditable;

        if (!isEditingControl) {
          navigate(`/alerts/${alert.id}/charts`);
        }
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [alert.id, visible.length, navigate]);

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
          {visible.length > 0 && (
            <button
              type="button"
              onClick={() => navigate(`/alerts/${alert.id}/charts`)}
              className={`flex items-center gap-1 ${tabClass(false)}`}
            >
              {t('companies.charts')}
              <span aria-hidden="true">→</span>
            </button>
          )}
        </div>
        {/* Group-by selector commented out per request -- keep groupMode
            defaulted to 'tier' (see useState above) rather than removing
            the grouping logic itself.
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
        */}
      </div>
      <SentimentBar companies={visible} />
      {grouped.length === 0 ? (
        <p className="text-xs text-muted">{emptyCopy}</p>
      ) : (
        grouped.map((group) => {
          const isOpen = openGroups[group.key] ?? false;
          return (
            <div key={group.key} className="flex flex-col gap-2">
              <button
                type="button"
                onClick={() => toggleGroup(group.key)}
                aria-expanded={isOpen}
                className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-xs uppercase tracking-widest outline-none transition-colors hover:bg-elevated/60 focus-visible:ring-1 focus-visible:ring-hairline ${headerClass(groupMode, group)}`}
              >
                <span
                  aria-hidden="true"
                  className="font-data text-[10px] transition-transform duration-150"
                  style={{ transform: isOpen ? 'rotate(90deg)' : 'none' }}
                >
                  ▸
                </span>
                {group.color && (
                  <span aria-hidden="true" className="h-2 w-2 rounded-full" style={{ backgroundColor: group.color }} />
                )}
                {groupMode === 'tier' ? group.label : `${group.label} · ${group.companies.length}`}
              </button>
              {isOpen && (
                <div className="flex flex-col">
                  {group.companies.map((company) => {
                    // Resolved against the alert's FULL company list, not
                    // just the currently-visible/filtered subset -- a
                    // Ripple company's parent can be filtered out of the
                    // My Portfolio tab while the ripple company itself
                    // (held) stays visible, and it should still show what
                    // it's linked via.
                    const parentCompany =
                      company.parent_company_id != null
                        ? alert.companies.find((c) => c.company_id === company.parent_company_id)
                        : undefined;
                    return (
                      <div
                        key={company.company_id}
                        className={groupMode !== 'tier' && company.basis === 'sector_inference' ? 'opacity-70' : undefined}
                      >
                        <CollapsibleInsightRow
                          company={company}
                          eventType={alert.event_type}
                          alertCreatedAt={alert.created_at}
                          alertId={alert.id}
                          parentCompany={parentCompany}
                        />
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}

