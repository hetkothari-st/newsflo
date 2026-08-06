/* v4 (i) glance popup -- the deployed shell's "glance and stay" info
   sheet in the broadsheet language: a small paper popup with the
   company's identity and its official BSE classification + ratios.
   Deliberately separate from the deep dive (row tap = go deep, (i) =
   glance), exactly like the deployed version. */
import type { Fundamentals } from '../lib/api';
import LogoV4 from './LogoV4';

export interface InfoV4Data {
  name: string;
  ticker: string;
  sector: string;
  logoUrl: string | null;
  fundamentals?: Fundamentals | null;
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
        {/* No fallback text: an unclassified company renders no section at
            all -- same omit-rather-than-invent rule as the deployed sheet. */}
        {classification.length > 0 && (
          <div className="layer4">
            <div className="lhead4">
              <span className="li4" aria-hidden="true">
                ◆
              </span>
              <span>What they do{info.fundamentals?.source ? ` — ${info.fundamentals.source}` : ''}</span>
            </div>
            <div className="lbody4">
              <p className="ddprose">{classification.join(' — ')}</p>
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
        <p className="dddisc">Glance view. Tap the row for the full impact breakdown.</p>
      </div>
    </div>
  );
}
