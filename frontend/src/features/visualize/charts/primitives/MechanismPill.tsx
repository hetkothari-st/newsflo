// A mechanism node reads as a step in a chain, not an entity like a company
// or sector -- fully rounded, smaller, muted, never bordered in an accent
// color.
export default function MechanismPill({ label }: { label: string }) {
  return (
    <span className="inline-flex max-w-[160px] items-center truncate rounded-full border border-hairline bg-elevated px-3 py-1 font-data text-[10px] uppercase tracking-widest text-muted">
      {label}
    </span>
  );
}
