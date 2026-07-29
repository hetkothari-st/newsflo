import { useState } from 'react';
import { avatarColor, sectorColor } from '../features/visualize/colors';

function initials(ticker: string): string {
  const base = ticker.split('.')[0];
  return base.slice(0, 2).toUpperCase();
}

const SIZE_CLASS = {
  sm: 'h-6 w-6 text-[9px]',
  md: 'h-11 w-11 text-sm',
  lg: 'h-16 w-16 text-lg',
} as const;

export default function CompanyLogo({
  logoUrl,
  ticker,
  size = 'md',
  sector,
}: {
  logoUrl?: string | null;
  ticker: string;
  size?: 'sm' | 'md' | 'lg';
  // Optional -- when known, the fallback avatar uses this company's real
  // sector color (the same hue its group-header dot/chart nodes already
  // use elsewhere), so a company with no logo art still reads as "this
  // specific real company", not a generic placeholder. Falls back to a
  // deterministic per-ticker color from the same validated palette when
  // the caller doesn't have a sector to hand.
  sector?: string | null;
}) {
  const [failed, setFailed] = useState(false);
  const showFallback = !logoUrl || failed;
  const fallbackColor = sector ? sectorColor(sector) : avatarColor(ticker);

  return (
    <span
      className={`flex shrink-0 items-center justify-center overflow-hidden ${
        showFallback ? '' : 'border border-hairline bg-page'
      } ${SIZE_CLASS[size]}`}
      style={showFallback ? { backgroundColor: fallbackColor } : undefined}
    >
      {showFallback ? (
        // A real, deliberate color (not a flat grey box) -- a company with
        // no logo art on file was reading as "disabled" next to companies
        // with real, colorful logos, purely from the old fallback's
        // near-zero contrast against the page background.
        <span className="font-data font-semibold text-white" aria-hidden="true">
          {initials(ticker)}
        </span>
      ) : (
        <img
          src={logoUrl}
          alt=""
          className="h-full w-full object-contain"
          onError={() => setFailed(true)}
        />
      )}
    </span>
  );
}
