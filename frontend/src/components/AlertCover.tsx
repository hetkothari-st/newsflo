import { useState } from 'react';

// Full static class strings (not built by interpolation) so Tailwind's content
// scanner keeps them -- same convention as CategorySwatch's SWATCH_CLASS,
// keyed by the same fixed category taxonomy (backend/app/analysis/schemas.py
// CATEGORIES).
const COVER_BG: Record<string, string> = {
  oil_gas: 'bg-swatch-oil_gas/10',
  banking: 'bg-swatch-banking/10',
  auto: 'bg-swatch-auto/10',
  it: 'bg-swatch-it/10',
  pharma: 'bg-swatch-pharma/10',
  fmcg: 'bg-swatch-fmcg/10',
  metals: 'bg-swatch-metals/10',
  telecom: 'bg-swatch-telecom/10',
  infra: 'bg-swatch-infra/10',
  macro_policy: 'bg-swatch-macro_policy/10',
  geopolitics: 'bg-swatch-geopolitics/10',
  corporate_event: 'bg-swatch-corporate_event/10',
  market_commentary: 'bg-swatch-market_commentary/10',
  other: 'bg-swatch-other/10',
};
const COVER_BG_FALLBACK = 'bg-swatch-other/10';

const GLYPH_BG: Record<string, string> = {
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
const GLYPH_BG_FALLBACK = 'bg-swatch-other';

// No real photo -- either the article's page had no og:image, or the scrape
// hasn't run for it yet. A quiet category-tinted cover keeps every card
// visually anchored instead of leaving a blank gap where a photo would go.
function CategoryCover({ category }: { category: string }) {
  const bgClass = COVER_BG[category] ?? COVER_BG_FALLBACK;
  const glyphClass = GLYPH_BG[category] ?? GLYPH_BG_FALLBACK;
  return (
    <div className={`flex h-full w-full items-center justify-center ${bgClass}`}>
      <span className={`h-10 w-10 rounded-full ${glyphClass} opacity-40`} aria-hidden="true" />
    </div>
  );
}

export default function AlertCover({ imageUrl, category }: { imageUrl: string | null; category: string }) {
  const [failed, setFailed] = useState(false);

  if (!imageUrl || failed) {
    return <CategoryCover category={category} />;
  }

  // The banner box (AlertCoverCard) is now tall/portrait-ish, while most
  // og:image thumbnails are landscape (~1.9:1) -- object-cover forced those
  // to fill the box's height, cropping out most of the width and showing
  // only a thin vertical sliver of the real photo. object-contain shows the
  // whole photo, uncropped, at full quality; a blurred copy of the same
  // photo fills the letterbox margins so the box still reads as filled
  // rather than leaving flat empty bars.
  return (
    <div className="relative h-full w-full overflow-hidden">
      <img
        src={imageUrl}
        alt=""
        aria-hidden="true"
        loading="lazy"
        onError={() => setFailed(true)}
        className="absolute inset-0 h-full w-full scale-110 object-cover blur-2xl motion-reduce:blur-md"
      />
      <img
        src={imageUrl}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
        className="relative h-full w-full object-contain"
      />
    </div>
  );
}
