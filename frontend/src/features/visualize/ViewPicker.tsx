export type ViewType = 'impact' | 'sector';

const VIEWS: { id: ViewType; label: string }[] = [
  { id: 'impact', label: 'Impact Tree' },
  { id: 'sector', label: 'Sector Tree' },
];

export default function ViewPicker({ value, onChange }: { value: ViewType; onChange: (v: ViewType) => void }) {
  return (
    <div className="flex gap-1 rounded-lg border border-hairline bg-surface p-1">
      {VIEWS.map((v) => (
        <button
          key={v.id}
          type="button"
          onClick={() => onChange(v.id)}
          className={`rounded-md px-3 py-1.5 text-xs uppercase tracking-widest motion-safe:transition-colors ${
            value === v.id ? 'bg-page text-ink' : 'text-muted hover:text-ink'
          }`}
        >
          {v.label}
        </button>
      ))}
    </div>
  );
}
