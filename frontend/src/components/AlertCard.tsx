import { useState, type KeyboardEvent, type MouseEvent } from 'react';
import type { Alert, AlertCompany } from '../lib/api';
import CategorySwatch from './CategorySwatch';
import CompanyChip from './CompanyChip';
import SentimentPill from './SentimentPill';
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

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function AlertCard({ alert, isAuthenticated }: { alert: Alert; isAuthenticated: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState<Tab>('predicted');
  const [visualizeOpen, setVisualizeOpen] = useState(false);

  const visible = tab === 'predicted' ? alert.companies : alert.companies.filter((c) => c.in_my_holdings);

  const grouped = TIER_ORDER.map((tier) => ({
    tier,
    label: TIER_LABEL[tier],
    companies: visible.filter((c) => tierKey(c) === tier),
  })).filter((g) => g.companies.length > 0);

  function toggleExpand() {
    setExpanded((v) => !v);
  }

  function onHeaderKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggleExpand();
    }
  }

  function selectTab(e: MouseEvent, next: Tab) {
    e.stopPropagation(); // tab click must not toggle the card
    setTab(next);
    setExpanded(true);
  }

  function openVisualize(e: MouseEvent) {
    e.stopPropagation(); // must not toggle the card, same reasoning as selectTab
    setVisualizeOpen(true);
  }

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
    <article className="rounded-lg border border-hairline bg-surface p-6">
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={toggleExpand}
        onKeyDown={onHeaderKeyDown}
        className="flex cursor-pointer flex-col gap-3"
      >
        <div className="flex items-center justify-between">
          <CategorySwatch category={alert.category} />
          <time className="text-xs uppercase tracking-widest text-muted">{formatTime(alert.created_at)}</time>
        </div>
        <h2 className="font-display text-xl font-bold leading-snug text-ink">{alert.article.title}</h2>
      </div>

      <div className="mt-4 flex items-center justify-between">
        <div className="flex gap-4">
          <button type="button" onClick={(e) => selectTab(e, 'predicted')} className={tabClass(tab === 'predicted')}>
            Predicted
          </button>
          <button type="button" onClick={(e) => selectTab(e, 'my_demat')} className={tabClass(tab === 'my_demat')}>
            My Portfolio
          </button>
        </div>
        <SentimentPill companies={visible} />
      </div>

      {expanded && (
        <div className="mt-4 flex flex-col gap-4 motion-safe:transition-all">
          <div className="flex justify-end">
            <button
              type="button"
              onClick={openVisualize}
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
        </div>
      )}
      {visualizeOpen && <VisualizeModal alert={alert} onClose={() => setVisualizeOpen(false)} />}
    </article>
  );
}
