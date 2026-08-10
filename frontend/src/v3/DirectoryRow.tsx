/* Presentational directory row (StockRow.tsx pattern) -- props in,
   onOpenDeepDive out, no data fetching. */
import type { DirectoryCompany } from './api';
import CompanyLogo from './CompanyLogo';
import { sectorLabel } from '../features/visualize/transforms';
import { displaySector } from './directoryFilters';
import { capClass, fmtMarketCapCr, fmtRatio } from './format';

const INDEX_BADGES: Record<string, string> = {
  NIFTY50: 'N50',
  NIFTY100: 'N100',
  NIFTY500: 'N500',
};

export default function DirectoryRow({
  company,
  onOpenDeepDive,
}: {
  company: DirectoryCompany;
  onOpenDeepDive: (ticker: string) => void;
}) {
  const indexBadge = INDEX_BADGES[company.index_tier];
  return (
    <div className="direntry" onClick={() => onOpenDeepDive(company.ticker)}>
      <CompanyLogo
        logoUrl={company.logo_url}
        ticker={company.ticker}
        sector={company.sector}
        size="sm"
      />
      <div>
        <div className="de-name">{company.name}</div>
        <div className="de-tk">
          {company.ticker} · {sectorLabel(displaySector(company))}
        </div>
      </div>
      <div className="de-right">
        <div className="de-figs">
          <div className="de-mcap">{fmtMarketCapCr(company.market_cap)}</div>
          <div className="de-pe">PE {fmtRatio(company.pe)}</div>
        </div>
        <div className="de-badges">
          {indexBadge !== undefined && <span className="tag idx">{indexBadge}</span>}
          <span className={`de-cap tag ${capClass(company.cap_tier)}`}>
            {company.cap_tier ?? '—'}
          </span>
        </div>
      </div>
    </div>
  );
}
