// Full static class strings (not built by interpolation) so Tailwind's content
// scanner keeps them. Keyed by the fixed category taxonomy
// (backend/app/analysis/schemas.py CATEGORIES) -- every value the LLM can
// emit has an entry here; the ?? fallbacks below exist only for a stray
// legacy value predating that taxonomy.
const SWATCH_CLASS: Record<string, string> = {
  oil_gas: 'bg-swatch-oil_gas',
  banking: 'bg-swatch-banking',
  auto: 'bg-swatch-auto',
  it: 'bg-swatch-it',
  pharma: 'bg-swatch-pharma',
  fmcg: 'bg-swatch-fmcg',
  metals: 'bg-swatch-metals',
  telecom: 'bg-swatch-telecom',
  infra: 'bg-swatch-infra',
  macro_policy: 'bg-swatch-macro_policy',
  geopolitics: 'bg-swatch-geopolitics',
  corporate_event: 'bg-swatch-corporate_event',
  market_commentary: 'bg-swatch-market_commentary',
  other: 'bg-swatch-other',
};

const CATEGORY_LABEL: Record<string, string> = {
  oil_gas: 'Oil & Gas',
  banking: 'Banking',
  auto: 'Auto',
  it: 'IT Services',
  pharma: 'Pharma',
  fmcg: 'FMCG',
  metals: 'Metals & Mining',
  telecom: 'Telecom',
  infra: 'Infrastructure',
  macro_policy: 'Macro & Policy',
  geopolitics: 'Geopolitics',
  corporate_event: 'Corporate Event',
  market_commentary: 'Market Commentary',
  other: 'Other',
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
    // actually take effect. `category` is enum-constrained at generation
    // time now (see CATEGORIES), but this stays as defense-in-depth for any
    // pre-existing/legacy row still holding an unrecognized value -- an
    // unclamped long one (once, literally a full sentence) wraps across
    // multiple lines and, since this sits in an absolutely-positioned
    // overlay, visually collides with the card's bottom-anchored headline
    // instead of pushing it down.
    <span className="inline-flex min-w-0 items-center gap-2">
      <span className={`h-2 w-2 shrink-0 rounded-full ${dotClass}`} aria-hidden="true" />
      <span className={`truncate text-xs uppercase tracking-widest ${active ? 'text-ink' : 'text-muted'}`}>
        {label}
      </span>
    </span>
  );
}
