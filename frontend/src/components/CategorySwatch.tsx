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

export default function CategorySwatch({
  category,
  active = false,
  label: translatedLabel,
}: {
  category: string;
  active?: boolean;
  // Server-translated display label for non-English languages (see
  // Alert.category_label / CategoryOption.label in lib/api.ts). Omitted (or
  // undefined) in English -- the client-side CATEGORY_LABEL map below still
  // wins there, unchanged from before this feature existed.
  label?: string;
}) {
  const dotClass = SWATCH_CLASS[category] ?? 'bg-swatch-other';
  const label = translatedLabel ?? CATEGORY_LABEL[category] ?? category.replace(/_/g, ' ');
  return (
    // min-w-0 lets this shrink below its content width inside the card's
    // top `justify-between` row (its `<time>` sibling otherwise forces it
    // to keep full intrinsic width) so `truncate` on the label below can
    // actually take effect. Categories are free-form LLM text with no
    // fixed taxonomy or length cap -- an unclamped long one (a full
    // sentence, not a short tag) wraps across multiple lines and, since
    // this sits in an absolutely-positioned overlay, visually collides
    // with the card's bottom-anchored headline instead of pushing it down.
    <span className="inline-flex min-w-0 items-center gap-2">
      <span className={`h-2 w-2 shrink-0 rounded-full ${dotClass}`} aria-hidden="true" />
      <span className={`truncate text-xs uppercase tracking-widest ${active ? 'text-ink' : 'text-muted'}`}>
        {label}
      </span>
    </span>
  );
}
