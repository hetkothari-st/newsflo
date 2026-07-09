// Full static class strings (not built by interpolation) so Tailwind's content
// scanner keeps them. Each maps a backend category to its named swatch color.
const SWATCH_CLASS: Record<string, string> = {
  oil_energy: 'bg-swatch-oil_energy',
  banking: 'bg-swatch-banking',
  auto_ev: 'bg-swatch-auto_ev',
  geopolitics: 'bg-swatch-geopolitics',
};

const CATEGORY_LABEL: Record<string, string> = {
  oil_energy: 'Oil & Energy',
  banking: 'Banking',
  auto_ev: 'Auto & EV',
  geopolitics: 'Geopolitics',
};

export default function CategorySwatch({ category }: { category: string }) {
  const dotClass = SWATCH_CLASS[category] ?? 'bg-swatch-other';
  const label = CATEGORY_LABEL[category] ?? category.replace(/_/g, ' ');
  return (
    <span className="inline-flex items-center gap-2">
      <span className={`h-2 w-2 rounded-full ${dotClass}`} aria-hidden="true" />
      <span className="text-xs uppercase tracking-widest text-muted">{label}</span>
    </span>
  );
}
