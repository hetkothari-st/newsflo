// Human-readable labels for rule ids (backend/app/reasoning/rulebook.py)
// and event types (backend/app/analysis/schemas.py::EVENT_TYPES). Kept in
// sync manually -- the frontend can't import backend Python, so this is a
// deliberate duplication, same tradeoff the backend itself makes between
// app/reasoning/confidence.py and app/calibration/blender.py for
// CALIBRATION_SAMPLE_THRESHOLD.

const RULE_LABELS: Record<string, string> = {
  RULE_REPO_RATE_CUT: 'Repo rate cut',
  RULE_REPO_RATE_HIKE: 'Repo rate hike',
  RULE_INFLATION_RISE: 'Inflation rise',
  RULE_CRUDE_OIL_UP: 'Crude oil up',
  RULE_CURRENCY_INR_WEAKENS: 'INR weakens',
  RULE_GOVERNMENT_CAPEX: 'Government capex',
  RULE_EARNINGS: 'Earnings',
  RULE_MERGER_ACQUISITION: 'Merger/acquisition',
  RULE_BANKING_METRICS: 'Banking metrics',
};

export function ruleLabel(ref: string): string {
  return RULE_LABELS[ref] ?? ref;
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  repo_rate_change: 'Repo rate change',
  inflation: 'Inflation',
  crude_oil: 'Crude oil',
  currency_move: 'Currency move',
  government_spending: 'Government spending',
  earnings: 'Earnings',
  merger_acquisition: 'Merger/acquisition',
  banking_metrics: 'Banking metrics',
  other: 'Other',
};

export function eventTypeLabel(type: string): string {
  return EVENT_TYPE_LABELS[type] ?? type;
}

export type EvidenceRefKind = 'rule' | 'article' | 'historical' | 'other';

export function formatEvidenceRef(ref: string): { text: string; kind: EvidenceRefKind } {
  if (ref.startsWith('RULE_')) {
    return { text: ruleLabel(ref), kind: 'rule' };
  }
  if (ref.startsWith('article:')) {
    return { text: ref.slice('article:'.length).trim(), kind: 'article' };
  }
  if (ref.startsWith('historical:')) {
    return { text: ref.slice('historical:'.length).trim(), kind: 'historical' };
  }
  return { text: ref, kind: 'other' };
}
