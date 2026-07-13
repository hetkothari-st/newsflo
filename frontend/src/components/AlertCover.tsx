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

  if (!imageUrl || failed) {
    return <CategoryCover category={category} />;
  }

  // A single object-cover fill, biased toward the top of the source photo
  // (object-top) since a news photo's subject is usually upper-frame while
  // captions/logos/signage sit lower -- cropping the bottom loses less than
  // a center crop would. Previously this stacked a blurred object-cover
  // backdrop behind a sharp object-contain foreground: on a tall mobile
  // card, a small/plain source image made the contain layer read as nearly
  // blank against the dominant blur, and the backdrop's own scale-110 crop
  // was visible around it -- worse on both fronts than a plain cover fill.
  return (
    <div className="relative h-full w-full overflow-hidden">
      <img
        src={imageUrl}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
        className="h-full w-full object-cover object-top"
      />
    </div>
  );
}
