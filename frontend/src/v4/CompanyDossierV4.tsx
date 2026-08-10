/* Company Dossier -- the Directory's full-page company report in the
   broadsheet language: nameplate with both exchange listings, live
   price band, sourced "what they do", five-year price rule, the
   company's own measured news record, sourced history/developments
   (when the enrichment pipeline has them), track record. Every section
   with no data disappears -- omit, never invent. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  getCompanyDossier,
  getLivePrice,
  getPriceSeries,
  indexLabel,
  type CompanyDossier,
  type LivePrice,
  type PricePoint,
} from './dossierApi';
import { formatMarketCap } from './directoryLiveCaps';
import LogoV4 from './LogoV4';
import '../v4/v4.css';

const IST_DATE = new Intl.DateTimeFormat('en-IN', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'Asia/Kolkata',
});

function fmtPct(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

/* Five-year close series as a broadsheet rule: single ink line, hairline
   baseline grid, serif endpoints. Direction color only on the numeral. */
function PriceRule({ points }: { points: PricePoint[] }) {
  const wrapRef = useRef<HTMLDivElement>(null!);
  const [width, setWidth] = useState(320);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    setWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);

  const H = 180;
  const PAD = 8;
  const closes = points.map((p) => p.close);
  const lo = Math.min(...closes);
  const hi = Math.max(...closes);
  const span = hi - lo || 1;
  const x = (i: number) => PAD + (i / Math.max(1, points.length - 1)) * (width - PAD * 2);
  const y = (close: number) => PAD + (1 - (close - lo) / span) * (H - PAD * 2);
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(p.close).toFixed(1)}`).join(' ');
  const first = points[0];
  const last = points[points.length - 1];
  const change = ((last.close - first.close) / first.close) * 100;

  return (
    <div ref={wrapRef} className="dscchart">
      <div className="dscchart-cap">
        <span>{IST_DATE.format(new Date(first.date))}</span>
        <b className={change < 0 ? 'down' : 'up'}>{fmtPct(change)} over five years</b>
        <span>{IST_DATE.format(new Date(last.date))}</span>
      </div>
      <svg width={width} height={H} viewBox={`0 0 ${width} ${H}`} role="img" aria-label="Five-year price history">
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} className="dsc-grid" x1={PAD} x2={width - PAD} y1={PAD + f * (H - PAD * 2)} y2={PAD + f * (H - PAD * 2)} />
        ))}
        <path className="dsc-line" d={path} />
      </svg>
      <div className="dscchart-cap">
        <span>₹{first.close.toFixed(0)}</span>
        <span>₹{last.close.toFixed(0)}</span>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="dsc-section">
      <div className="lhead4">
        <span className="li4" aria-hidden="true">
          ◆
        </span>
        <span>{title}</span>
      </div>
      <div className="lbody4">{children}</div>
    </section>
  );
}

export default function CompanyDossierV4() {
  const { ticker = '' } = useParams<{ ticker: string }>();
  const navigate = useNavigate();
  const [dossier, setDossier] = useState<CompanyDossier | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [series, setSeries] = useState<PricePoint[] | null>(null);
  const [live, setLive] = useState<LivePrice | null>(null);
  const dark = localStorage.getItem('newsflo.v4.theme') === 'dark';

  useEffect(() => {
    let cancelled = false;
    getCompanyDossier(ticker)
      .then((result) => {
        if (!cancelled) setDossier(result);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  useEffect(() => {
    if (dossier === null) return;
    let cancelled = false;
    getPriceSeries(dossier.id, '5y')
      .then((result) => {
        if (!cancelled && result.available && result.points.length >= 2) setSeries(result.points);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [dossier]);

  // Live price: 5s poll, same cadence as the directory ranking.
  useEffect(() => {
    if (dossier === null) return;
    let active = true;
    const poll = () => {
      getLivePrice(dossier.id)
        .then((result) => {
          if (active) setLive(result);
        })
        .catch(() => {});
    };
    poll();
    const id = window.setInterval(poll, 5000);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, [dossier]);

  const ratios = dossier?.fundamentals?.ratios ?? {};
  const ratioCells = useMemo(
    () =>
      (
        [
          ['pe', 'P/E'],
          ['pb', 'P/B'],
          ['roe', 'ROE'],
          ['opm', 'OPM'],
        ] as const
      ).filter(([key]) => ratios[key] != null),
    [ratios],
  );
  const classification = dossier?.fundamentals
    ? [
        dossier.fundamentals.classification.sector,
        dossier.fundamentals.classification.industry,
        dossier.fundamentals.classification.group,
        dossier.fundamentals.classification.sub_group,
      ].filter(Boolean)
    : [];
  const nse = dossier?.listings.find((l) => l.exchange === 'NSE');
  const bse = dossier?.listings.find((l) => l.exchange === 'BSE');
  const track = dossier?.track_record ?? null;
  const trackCells = track
    ? (Object.entries(track) as Array<[string, { win_rate: number; sample_size: number }]>).filter(
        ([, v]) => v != null,
      )
    : [];

  return (
    <div className={`nf4 dossierpage ${dark ? 'dark' : ''}`}>
      <header className="cpage-head">
        <button className="cpage-back" onClick={() => navigate('/v4')}>
          ← Directory
        </button>
        <div className="cpage-kicker">Company dossier</div>
      </header>

      {error !== null && <p className="empty4">{error}</p>}
      {dossier === null && error === null && (
        <div className="ddloading" aria-busy="true">
          <span className="ddload-rule" />
          <p>Loading…</p>
          <span className="ddload-rule" />
        </div>
      )}

      {dossier !== null && (
        <div className="dsc-body">
          {/* Nameplate */}
          <div className="dsc-nameplate">
            <LogoV4 logoUrl={dossier.logo_url} ticker={dossier.ticker} name={dossier.name} size="md" />
            <h1 className="dsc-name">{dossier.name}</h1>
            <div className="dsc-symbols">
              {nse && <span>NSE {nse.symbol}</span>}
              {bse && <span>BSE {bse.scrip_code ?? bse.symbol}</span>}
              <span>{dossier.sector.replace(/_/g, ' ')}</span>
              {dossier.cap_tier && <span className="gtag">{dossier.cap_tier}</span>}
            </div>
            {dossier.indices.length > 0 && (
              <div className="dsc-indices">
                {dossier.indices.map((code) => (
                  <span className="gtag" key={code}>
                    {indexLabel(code)}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Price band: live numeral when the tape is on, cap always */}
          <div className="sumline dsc-priceband">
            {live?.available && live.ltp != null && (
              <span>
                Last traded
                <b className={live.change_pct != null && live.change_pct < 0 ? 'down' : 'up'}>
                  ₹{live.ltp.toFixed(2)}
                  {live.change_pct != null ? ` (${fmtPct(live.change_pct)})` : ''}
                </b>
              </span>
            )}
            {dossier.market_cap != null && (
              <span>
                Market cap
                <b>
                  {formatMarketCap(dossier.market_cap)}
                  {dossier.market_cap_source === 'live' ? ' · live' : ''}
                </b>
              </span>
            )}
            {ratioCells.map(([key, label]) => (
              <span key={key}>
                {label}
                <b>{ratios[key]!.toFixed(1)}</b>
              </span>
            ))}
          </div>

          {(dossier.business_desc || classification.length > 0) && (
            <Section title={`What they do${dossier.fundamentals?.source ? ` — ${dossier.fundamentals.source}` : ''}`}>
              {dossier.business_desc && (
                <p className="ddprose">
                  {dossier.business_desc}
                  {dossier.business_desc_source_url && (
                    <>
                      {' '}
                      <a className="ddsource" href={dossier.business_desc_source_url} target="_blank" rel="noreferrer">
                        source
                      </a>
                    </>
                  )}
                </p>
              )}
              {classification.length > 0 && <p className="ddprose ddclass">{classification.join(' — ')}</p>}
            </Section>
          )}

          {dossier.history_text && (
            <Section title="The story so far">
              <p className="ddprose">
                {dossier.history_text}
                {dossier.history_source_url && (
                  <>
                    {' '}
                    <a className="ddsource" href={dossier.history_source_url} target="_blank" rel="noreferrer">
                      source
                    </a>
                  </>
                )}
              </p>
            </Section>
          )}

          {series !== null && (
            <Section title="Five years on the tape">
              <PriceRule points={series} />
            </Section>
          )}

          {dossier.developments_text && (
            <Section title="Recent developments">
              <p className="ddprose">
                {dossier.developments_text}
                {dossier.developments_source_url && (
                  <>
                    {' '}
                    <a className="ddsource" href={dossier.developments_source_url} target="_blank" rel="noreferrer">
                      source
                    </a>
                  </>
                )}
              </p>
            </Section>
          )}

          {dossier.news.length > 0 && (
            <Section title="In the news — measured record">
              {dossier.news.map((item) => (
                <a className="dsc-newsrow" key={item.alert_id} href={item.url} target="_blank" rel="noreferrer">
                  <span className="dsc-newsdate">{IST_DATE.format(new Date(item.created_at))}</span>
                  <span className="dsc-newstitle">{item.title}</span>
                  {item.excess_move_pct != null ? (
                    <b className={`dsc-newsmove ${item.excess_move_pct < 0 ? 'down' : 'up'}`}>
                      {fmtPct(item.excess_move_pct)}
                    </b>
                  ) : (
                    <span className="dsc-newsmove flat">—</span>
                  )}
                </a>
              ))}
            </Section>
          )}

          {trackCells.length > 0 && (
            <Section title="Our record on this name">
              <div className="sumline">
                {trackCells.map(([horizon, value]) => (
                  <span key={horizon}>
                    {horizon}-day calls
                    <b>{Math.round(value.win_rate * 100)}% held</b>
                  </span>
                ))}
              </div>
              <p className="dddisc">
                Share of our direction calls the market confirmed at each horizon. Sample sizes are small —
                a record, not a promise.
              </p>
            </Section>
          )}

          <p className="dddisc">
            Everything above is sourced: exchange records, BSE filings, measured market reactions, and
            attributed text. Missing sections mean missing data — never filler.
          </p>
        </div>
      )}
    </div>
  );
}
