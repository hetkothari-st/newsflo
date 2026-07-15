import type { LivePrice } from '../lib/api';
import { useLanguage } from '../lib/language';

export default function LivePriceReadout({ price }: { price: LivePrice }) {
  const { t } = useLanguage();

  if (!price.available || price.ltp === null) {
    return <p className="text-xs text-muted">{t('company.livePriceUnavailable')}</p>;
  }

  const changePct = price.change_pct;
  const bullish = (changePct ?? 0) >= 0;

  return (
    <div className="flex items-baseline gap-2">
      <span className="font-display text-3xl font-bold text-ink">₹{price.ltp.toFixed(2)}</span>
      {changePct !== null && (
        <span className={`text-sm ${bullish ? 'text-bullish' : 'text-bearish'}`}>
          {bullish ? '+' : ''}
          {changePct.toFixed(2)}%
        </span>
      )}
    </div>
  );
}
