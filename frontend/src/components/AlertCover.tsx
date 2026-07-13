import { useState } from 'react';

// Full static class strings (not built by interpolation) so Tailwind's content
// scanner keeps them -- same convention as CategorySwatch's SWATCH_CLASS.
const COVER_BG: Record<string, string> = {
  oil_energy: 'bg-swatch-oil_energy/10',
  banking: 'bg-swatch-banking/10',
  auto_ev: 'bg-swatch-auto_ev/10',
  geopolitics: 'bg-swatch-geopolitics/10',
};
const COVER_BG_FALLBACK = 'bg-swatch-other/10';

const GLYPH_BG: Record<string, string> = {
  oil_energy: 'bg-swatch-oil_energy',
  banking: 'bg-swatch-banking',
  auto_ev: 'bg-swatch-auto_ev',
  geopolitics: 'bg-swatch-geopolitics',
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
  const bgClass = COVER_BG[category] ?? COVER_BG_FALLBACK;

  if (!imageUrl || failed) {
    return <CategoryCover category={category} />;
  }

  // Scraped og:image thumbnails (typically ~600-1200px wide) are far lower
  // resolution than the tall full-bleed mobile card they'd need to fill --
  // stretching one edge-to-edge upscales it well past its real detail,
  // reading as blurry/pixelated. A blurred duplicate as backdrop (the prior
  // approach) traded that for a different complaint: a hazy, washed-out
  // blob dominating most of the card. A flat category-tinted backdrop (the
  // same one the no-image fallback uses) behind the untouched, natural-size
  // photo keeps every pixel of the real photo crisp with no blur anywhere.
  return (
    <div className={`flex h-full w-full items-center justify-center p-6 ${bgClass}`}>
      <img
        src={imageUrl}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
        className="max-h-full max-w-full rounded-lg object-contain shadow-2xl"
      />
    </div>
  );
}
