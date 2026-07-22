import type { ReactNode } from 'react';

// Structural signature of the level-band tree charts (1, 4, 5): a centered
// label with a hairline rule running to both card edges, then a centered,
// wrapping row of nodes beneath it. flex-wrap + justify-center means this
// renders identically whether the row holds one node or eight -- a single
// child centers under the full-width band exactly like the reference
// mockup, never collapsing to a left-aligned line or hiding the band.
export default function LevelBand({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex w-full flex-col items-center gap-3">
      <div className="flex w-full items-center gap-3">
        <span aria-hidden="true" className="h-px flex-1 bg-hairline" />
        <span className="shrink-0 font-data text-[10px] uppercase tracking-widest text-muted">{label}</span>
        <span aria-hidden="true" className="h-px flex-1 bg-hairline" />
      </div>
      <div className="flex w-full flex-wrap items-start justify-center gap-2.5">{children}</div>
    </div>
  );
}
