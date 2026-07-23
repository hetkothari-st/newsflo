import { formatExcess, intensityBandColorClass, relationshipLabel } from '../../lib/feedV2Format';
import type { RippleCompany, RippleRelationship } from '../../lib/feedV2Api';

interface RippleSectionProps {
  companies: RippleCompany[];
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

export default function RippleSection({ companies }: RippleSectionProps) {
  if (companies.length === 0) return null;

  const groups = GROUP_ORDER.map((relationship) => ({
    relationship,
    rows: companies.filter((c) => c.relationship === relationship),
  })).filter((g) => g.rows.length > 0);

  return (
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
            <div className="mt-2 flex flex-col gap-2">
              {group.rows.map((row) => (
                <div key={row.ticker} className="flex items-center gap-3">
                  <span className="font-data text-[11px] text-muted">{row.ticker}</span>
                  {row.is_exposure_only || row.excess_move_pct == null ? (
                    <span className="font-sans text-xs text-muted">Exposure</span>
                  ) : (
                    <>
                      <span
                        className={`font-data text-xs ${
                          row.direction === 'bullish' ? 'text-bullish' : 'text-bearish'
                        }`}
                      >
                        {formatExcess(row.excess_move_pct).text}
                      </span>
                      {row.intensity && (
                        <span className="h-1 w-full max-w-[80px] rounded-sm bg-elevated">
                          <span
                            className={`block h-full rounded-sm ${intensityBandColorClass(row.intensity.band)}`}
                            style={{ width: `${row.intensity.score}%` }}
                          />
                        </span>
                      )}
                    </>
                  )}
                  {row.in_my_holdings && (
                    <span
                      data-testid="ripple-owned-dot"
                      className="h-[7px] w-[7px] shrink-0 rounded-full bg-accent"
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
