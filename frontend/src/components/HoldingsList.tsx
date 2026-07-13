import type { Holding } from '../lib/api';
import { useLanguage } from '../lib/language';

export default function HoldingsList({ holdings }: { holdings: Holding[] }) {
  const { t } = useLanguage();
  if (holdings.length === 0) {
    return <p className="text-xs uppercase tracking-widest text-muted">{t('holdings.empty')}</p>;
  }
  return (
    <ul className="flex flex-col divide-y divide-hairline rounded-lg border border-hairline">
      {holdings.map((h) => (
        <li key={h.company_id} className="flex items-center justify-between px-4 py-3">
          <span className="flex flex-col">
            <span className="text-sm text-ink">{h.name}</span>
            <span className="text-xs uppercase tracking-widest text-muted">{h.ticker}</span>
          </span>
          <span className="text-sm tabular-nums text-ink">{h.quantity}</span>
        </li>
      ))}
    </ul>
  );
}
