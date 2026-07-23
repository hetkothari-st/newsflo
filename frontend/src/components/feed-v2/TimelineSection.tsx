import type { TimelineEntry } from '../../lib/feedV2Api';

interface TimelineSectionProps {
  entries: TimelineEntry[];
}

const HORIZON_LABELS: Record<string, string> = {
  TODAY: 'Today',
  DAYS: 'Next few days',
  WEEKS: 'Next few weeks',
  MONTHS: 'Next few months',
  QUARTERS: 'Next few quarters',
};

export default function TimelineSection({ entries }: TimelineSectionProps) {
  if (entries.length === 0) return null;

  return (
    <div className="rounded-lg bg-surface p-5">
      <div className="flex flex-col gap-4 border-l-2 border-hairline pl-4">
        {entries.map((entry) => (
          <div key={entry.horizon} className="relative">
            <span className="absolute -left-[21px] top-1 h-2 w-2 rounded-full bg-accent" />
            <div className="font-sans text-[11px] uppercase tracking-widest text-muted">
              {HORIZON_LABELS[entry.horizon] ?? entry.horizon}
            </div>
            <p className="mt-1 font-sans text-[13px] text-ink">{entry.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
