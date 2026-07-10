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

// The model's rationale is a full paragraph (deliberately kept rich — that
// depth is the point). Splitting it into one bullet per sentence keeps every
// word but makes it scannable instead of a wall of text. Sentence-boundary
// heuristic (period/!/? followed by a capital letter), not real NLP — good
// enough for display, and a mis-split just means two bullets instead of one.
export function splitRationaleIntoPoints(rationale: string): string[] {
  return rationale
    .split(/(?<=[.!?])\s+(?=[A-Z(])/)
    .map((point) => point.trim())
    .filter(Boolean);
}

export default function ReasoningPanel({ company }: { company: AlertCompany }) {
  // key_points is the model's own short, terse summary -- prefer it. Fall
  // back to sentence-splitting the full rationale only for alerts analyzed
  // before key_points existed (empty array).
  const points = company.key_points.length > 0 ? company.key_points : splitRationaleIntoPoints(company.rationale);
  return (
    <div className="rounded-lg border border-hairline bg-surface px-3 py-3">
      <p className="text-xs uppercase tracking-widest text-muted">
        {company.name} · {company.ticker}
      </p>
      <ul className="mt-2 space-y-1.5 text-sm text-ink">
        {points.map((point, i) => (
          <li key={i} className="flex gap-2">
            <span className="text-muted" aria-hidden="true">•</span>
            <span>{point}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">{precedentLine(company)}</p>
    </div>
  );
}
