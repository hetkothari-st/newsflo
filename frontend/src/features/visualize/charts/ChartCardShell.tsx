import type { ReactNode } from 'react';

export interface ChartLegendItem {
  label: string;
  color: string;
}

export default function ChartCardShell({
  number,
  title,
  description,
  legend,
  accentColor,
  children,
}: {
  number: number;
  title: string;
  description: string;
  legend?: ChartLegendItem[];
  // Badge fill color -- one per chart, drawn from the existing sector/
  // relation palette by each chart (never a new, unvalidated hex). Falls
  // back to a neutral hairline-bordered badge when omitted, so callers
  // that haven't picked an accent yet don't regress to an unstyled badge.
  accentColor?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-hairline bg-surface p-5 theme-light:border-transparent theme-light:shadow-neu">
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className={`flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${
            accentColor ? 'text-white' : 'border border-hairline text-muted'
          }`}
          style={accentColor ? { backgroundColor: accentColor } : undefined}
        >
          {number}
        </span>
        <div className="flex flex-col gap-0.5">
          <p className="text-[15px] font-semibold text-ink">{title}</p>
          <p className="text-xs text-muted">{description}</p>
        </div>
      </div>
      {children}
      {legend && legend.length > 0 && (
        <div data-testid="chart-legend" className="flex flex-wrap gap-3 border-t border-hairline pt-3 text-[11px] text-muted">
          {legend.map((item) => (
            <span key={item.label} className="inline-flex items-center gap-1.5">
              <span aria-hidden="true" className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
              {item.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
