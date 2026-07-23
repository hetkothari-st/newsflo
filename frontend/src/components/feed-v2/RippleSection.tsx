import { useState } from 'react';
import { relationshipLabel } from '../../lib/feedV2Format';
import type { RippleCompany, RippleRelationship } from '../../lib/feedV2Api';
import AlertDetail from '../AlertDetail';
import BusinessPopup from './BusinessPopup';
import PeerRow from './PeerRow';

interface RippleSectionProps {
  companies: RippleCompany[];
  alertId: number;
}

const GROUP_ORDER: RippleRelationship[] = [
  'BENEFICIARY',
  'CUSTOMER_INPUT_COST',
  'SUPPLIER',
  'SUBSTITUTE',
  'COMPETITOR',
  'SECTOR_WIDE',
];

function groupBorderColorClass(rows: RippleCompany[]): string {
  const bullishCount = rows.filter((r) => r.direction === 'bullish').length;
  const bearishCount = rows.length - bullishCount;
  return bullishCount >= bearishCount ? 'border-bullish' : 'border-bearish';
}

export default function RippleSection({ companies, alertId }: RippleSectionProps) {
  const [businessPopupTicker, setBusinessPopupTicker] = useState<string | null>(null);

  if (companies.length === 0) return null;

  const groups = GROUP_ORDER.map((relationship) => ({
    relationship,
    rows: companies.filter((c) => c.relationship === relationship),
  })).filter((g) => g.rows.length > 0);

  const popupCompany = companies.find((c) => c.ticker === businessPopupTicker) ?? null;

  return (
    <>
      <div className="rounded-lg bg-surface p-5">
        <div className="flex flex-col gap-4">
          {groups.map((group) => (
            <div
              key={group.relationship}
              className={`rounded-none border-l-2 pl-3 ${groupBorderColorClass(group.rows)}`}
            >
              <div className="font-sans text-[11px] uppercase tracking-widest text-muted">
                {relationshipLabel(group.relationship)} ({group.rows.length})
              </div>
              <div className="mt-2 flex flex-col gap-1">
                {group.rows.map((row) => (
                  <PeerRow
                    key={row.ticker}
                    ticker={row.ticker}
                    capTier={row.cap_tier}
                    direction={row.direction}
                    excessMovePct={row.excess_move_pct}
                    intensity={row.intensity}
                    isExposureOnly={row.is_exposure_only}
                    inMyHoldings={row.in_my_holdings}
                    alertId={alertId}
                    onOpenBusinessPopup={() => setBusinessPopupTicker(row.ticker)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      <AlertDetail open={popupCompany !== null} onClose={() => setBusinessPopupTicker(null)}>
        {popupCompany && (
          <BusinessPopup
            ticker={popupCompany.ticker}
            sector={popupCompany.sector}
            capTier={popupCompany.cap_tier}
            businessDesc={popupCompany.business_desc}
          />
        )}
      </AlertDetail>
    </>
  );
}
