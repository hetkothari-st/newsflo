import { useState } from 'react';
import type { Alert, AlertCompany } from '../lib/api';
import CompanyChip from './CompanyChip';
import VisualizeModal from '../features/visualize/VisualizeModal';

type Tab = 'predicted' | 'my_demat';

const TIER_ORDER = ['NIFTY50', 'NIFTY100', 'NIFTY500', 'OTHER'] as const;
const TIER_LABEL: Record<string, string> = {
  NIFTY50: 'Nifty 50',
  NIFTY100: 'Nifty 100',
  NIFTY500: 'Nifty 500',
  OTHER: 'Other',
};

function tierKey(company: AlertCompany): string {
  return TIER_LABEL[company.index_tier] ? company.index_tier : 'OTHER';
}

export default function AlertCompanies({
  alert,
  isAuthenticated,
}: {
  alert: Alert;
  isAuthenticated: boolean;
}) {
  const [tab, setTab] = useState<Tab>('predicted');
  const [visualizeOpen, setVisualizeOpen] = useState(false);

  const visible = tab === 'predicted' ? alert.companies : alert.companies.filter((c) => c.in_my_holdings);

  const grouped = TIER_ORDER.map((tier) => ({
    tier,
    label: TIER_LABEL[tier],
    companies: visible.filter((c) => tierKey(c) === tier),
  })).filter((g) => g.companies.length > 0);

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
        <button
          type="button"
          onClick={() => setVisualizeOpen(true)}
          className="text-xs uppercase tracking-widest text-muted hover:text-ink"
        >
          Visualize →
        </button>
      </div>
      {visible.length === 0 ? (
        <p className="text-xs text-muted">{emptyCopy}</p>
      ) : (
        grouped.map((group) => (
          <div key={group.tier} className="flex flex-col gap-2">
            <p className="text-xs uppercase tracking-widest text-muted">{group.label}</p>
            <div className="grid grid-cols-1 items-start gap-2 sm:grid-cols-2">
              {group.companies.map((company) => (
                <CompanyChip key={company.company_id} company={company} />
              ))}
            </div>
          </div>
        ))
      )}
      {visualizeOpen && <VisualizeModal alert={alert} onClose={() => setVisualizeOpen(false)} />}
    </div>
  );
}
