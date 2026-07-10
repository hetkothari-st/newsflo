import type { AlertCompany } from '../lib/api';

// Spec fallback rule: once the calibration DB has enough samples the confidence
// is "calibrated" and the direction is framed as historical precedent;
// otherwise the LLM's own estimate stands. Magnitude percentages are
// deliberately not shown -- they're frequently inaccurate and would overstate
// precision the model doesn't actually have.
export function precedentLine(company: AlertCompany): string {
  if (company.confidence === 'calibrated') {
    return `Historical precedent: similar past events showed a comparable ${company.direction} move over comparable horizons.`;
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
