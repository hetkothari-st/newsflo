/* v4 (i) glance popup -- the deployed shell's "glance and stay" info
   sheet in the broadsheet language, at full parity with it: the sourced
   business description (with attribution), the official BSE
   classification + key ratios, and the empirical volatility range.
   Deliberately separate from the deep dive (row tap = go deep, (i) =
   glance). A company with none of these renders no body section at all
   -- omit, never invent. */
import type { Fundamentals } from '../lib/api';
import type { VolatilityRangeData } from '../components/VolatilityRange';
import LogoV4 from './LogoV4';
import VolRangeV4 from './VolRangeV4';

export interface InfoV4Data {
  name: string;
  ticker: string;
  sector: string;
  logoUrl: string | null;
  fundamentals?: Fundamentals | null;
  businessDesc?: string | null;
  businessDescSourceUrl?: string | null;
  volatilityRange?: VolatilityRangeData | null;
}

const RATIO_LABELS: Array<{ key: 'pe' | 'pb' | 'roe' | 'opm' | 'npm' | 'eps'; label: string }> = [
  { key: 'pe', label: 'PE' },
  { key: 'pb', label: 'PB' },
  { key: 'roe', label: 'ROE' },
  { key: 'opm', label: 'OPM' },
  { key: 'npm', label: 'NPM' },
  { key: 'eps', label: 'EPS' },
];

export default function InfoV4({ info, onClose }: { info: InfoV4Data; onClose: () => void }) {
  const classification = info.fundamentals
    ? [
        info.fundamentals.classification.sector,
        info.fundamentals.classification.industry,
        info.fundamentals.classification.group,
        info.fundamentals.classification.sub_group,
      ].filter(Boolean)
    : [];
  const ratios = info.fundamentals?.ratios ?? {};
  const shownRatios = RATIO_LABELS.filter(({ key }) => ratios[key] != null);
  const hasWhat = classification.length > 0 || Boolean(info.businessDesc);
  const range = info.volatilityRange;

  return (
    <div className="ddscrim" onClick={onClose}>
      <div
        className="ddpop"
        role="dialog"
        aria-label={`About ${info.ticker}`}
        onClick={(event) => event.stopPropagation()}
      >
        <button className="bandclose" onClick={onClose}>
          Close ×
        </button>
        <div className="ddhead">
          <LogoV4 logoUrl={info.logoUrl} ticker={info.ticker} name={info.name} size="md" />
          <div>
            <div className="ddname">{info.name}</div>
            <div className="ddmeta">
              <span>{info.ticker}</span>
              <span>{info.sector.replace(/_/g, ' ')}</span>
            </div>
          </div>
        </div>
        {hasWhat && (
          <div className="layer4">
            <div className="lhead4">
              <span className="li4" aria-hidden="true">
                ◆
              </span>
              <span>What they do{info.fundamentals?.source ? ` — ${info.fundamentals.source}` : ''}</span>
            </div>
            <div className="lbody4">
              {info.businessDesc && (
                <p className="ddprose">
                  {info.businessDesc}
                  {info.businessDescSourceUrl && (
                    <>
                      {' '}
                      <a
                        className="ddsource"
                        href={info.businessDescSourceUrl}
                        target="_blank"
                        rel="noreferrer"
                      >
                        source
                      </a>
                    </>
                  )}
                </p>
              )}
              {classification.length > 0 && <p className="ddprose">{classification.join(' — ')}</p>}
            </div>
          </div>
        )}
        {shownRatios.length > 0 && (
          <div className="sumline infosum">
            {shownRatios.slice(0, 3).map(({ key, label }) => (
              <span key={key}>
                {label}
                <b>{ratios[key]!.toFixed(1)}</b>
              </span>
            ))}
          </div>
        )}
        {range && (
          <div className="layer4">
            <div className="lhead4">
              <span className="li4" aria-hidden="true">
                ◆
              </span>
              <span>Typical on this news type</span>
            </div>
            <div className="lbody4">
              <VolRangeV4 range={range} />
            </div>
          </div>
        )}
        <p className="dddisc">Glance view. Tap the row for the full impact breakdown.</p>
      </div>
    </div>
  );
}
