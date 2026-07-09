import type { AlertCompany } from '../lib/api';

function fmtPct(v: number): string {
  return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;
}

// Spec fallback rule: once the calibration DB has enough samples the confidence
// is "calibrated" and the blended range is framed as historical precedent;
// otherwise the LLM's own estimate stands.
export function precedentLine(company: AlertCompany): string {
  if (company.confidence === 'calibrated') {
    return `Historical precedent: similar past events averaged ${fmtPct(company.magnitude_low)} to ${fmtPct(
      company.magnitude_high,
    )} over comparable horizons.`;
  }
  return `No calibrated history yet — showing the model's own estimate.`;
}

export default function ReasoningPanel({ company }: { company: AlertCompany }) {
  return (
    <div className="rounded-lg border border-hairline bg-surface px-3 py-3">
      <p className="text-xs uppercase tracking-widest text-muted">
        {company.name} · {company.ticker}
      </p>
      <p className="mt-2 text-sm text-ink">{company.rationale}</p>
      <p className="mt-2 text-xs text-muted">{precedentLine(company)}</p>
    </div>
  );
}
