import { Link } from 'react-router-dom';
import type { AlertCompany } from '../lib/api';
import { precedentLine, splitRationaleIntoPoints } from '../lib/reasoning';
import { useLanguage } from '../lib/language';
import MentionRow from './MentionRow';

// Re-exported so this stays the one import path components/tests already use.
export { precedentLine, splitRationaleIntoPoints };

export default function ReasoningPanel({ company }: { company: AlertCompany }) {
  const { language, t } = useLanguage();
  // key_points is the model's own short, terse summary -- prefer it. Fall
  // back to sentence-splitting the full rationale only for alerts analyzed
  // before key_points existed (empty array).
  const points = company.key_points.length > 0 ? company.key_points : splitRationaleIntoPoints(company.rationale);
  return (
    <div className="rounded-lg border border-hairline bg-surface px-3 py-3">
      <p className="text-xs uppercase tracking-widest text-muted">
        {company.name} · {company.ticker}
      </p>
      <ul className="mt-2 space-y-1.5 text-sm text-ink">
        {points.map((point, i) => (
          <li key={i} className="flex gap-2">
            <span className="text-muted" aria-hidden="true">•</span>
            <span>{point}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">{precedentLine(company, language)}</p>
      {company.past_mentions.length > 0 && (
        <div className="mt-3 border-t border-hairline pt-2">
          <p className="text-xs uppercase tracking-widest text-muted">{t('reasoning.previously')}</p>
          <ul className="mt-1.5 space-y-1">
            {company.past_mentions.map((mention) => (
              <MentionRow key={mention.alert_id} mention={mention} />
            ))}
          </ul>
        </div>
      )}
      {company.market === 'IN' && (
        <Link
          to={`/company/${company.company_id}`}
          className="mt-3 inline-block text-xs uppercase tracking-widest text-ink underline"
        >
          {t('reasoning.viewDetails')}
        </Link>
      )}
    </div>
  );
}
