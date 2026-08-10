/* Small round company logo for the card-feed UI, with the same
   deliberate-color initials fallback as components/CompanyLogo.tsx (a
   company with no logo art must still read as a real company, not a
   disabled placeholder) -- restyled for the v3 shell's own CSS. */
import { useState } from 'react';
import { avatarColor, sectorColor } from '../features/visualize/colors';

function initials(ticker: string): string {
  return ticker.split('.')[0].slice(0, 2).toUpperCase();
}

export default function CompanyLogo({
  logoUrl,
  ticker,
  sector,
  size = 'sm',
}: {
  logoUrl?: string | null;
  ticker: string;
  sector?: string | null;
  size?: 'sm' | 'md';
}) {
  const [failed, setFailed] = useState(false);
  const showFallback = !logoUrl || failed;
  const fallbackColor = sector ? sectorColor(sector) : avatarColor(ticker);

  return (
    <span
      className={`clogo clogo-${size}`}
      style={showFallback ? { backgroundColor: fallbackColor } : undefined}
      data-testid={`clogo-${ticker}`}
    >
      {showFallback ? (
        <span aria-hidden="true">{initials(ticker)}</span>
      ) : (
        // lazy: the Directory mounts 1000+ rows at once -- eager loads
        // burst the logo CDN into 429s; offscreen rows must not fetch.
        <img
          src={logoUrl ?? undefined}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
        />
      )}
    </span>
  );
}
