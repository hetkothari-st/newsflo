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
  children,
}: {
  number: number;
  title: string;
  description: string;
  legend?: ChartLegendItem[];
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-3 px-4 pt-4">
        <span
          aria-hidden="true"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-hairline text-[11px] text-muted"
        >
          {number}
        </span>
        <div className="flex flex-col gap-0.5">
          <p className="text-sm font-medium text-ink">{title}</p>
          <p className="text-xs text-muted">{description}</p>
        </div>
      </div>
      {children}
      {legend && legend.length > 0 && (
        <div data-testid="chart-legend" className="flex flex-wrap gap-3 border-t border-hairline px-4 py-3 text-[11px] text-muted">
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
