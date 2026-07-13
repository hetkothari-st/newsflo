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

  // Scraped og:image thumbnails (typically ~600x315) are far lower-res than
  // the tall mobile card they fill -- a single object-cover layer forces the
  // browser to upscale the sharp image well past its real detail, reading as
  // blurry/pixelated (confirmed: this is what a plain object-cover fill
  // produced). A blurred object-cover backdrop fills the full bleed (blur
  // hides its own upscale softness, reads as intentional rather than a
  // quality bug), while the foreground uses the image's OWN natural size --
  // max-width/max-height:100% with no explicit width/height means the
  // browser never enlarges it past that size, only shrinks it if it doesn't
  // fit, so it's mathematically guaranteed to stay sharp regardless of how
  // tall the card is.
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
      <div className="relative flex h-full w-full items-center justify-center">
        <img src={imageUrl} alt="" loading="lazy" onError={() => setFailed(true)} className="max-h-full max-w-full" />
      </div>
    </div>
  );
}
