import { useState } from 'react';

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
}: {
  logoUrl?: string | null;
  ticker: string;
  size?: 'sm' | 'md' | 'lg';
}) {
  const [failed, setFailed] = useState(false);
  const showFallback = !logoUrl || failed;

  return (
    <span
      className={`flex shrink-0 items-center justify-center overflow-hidden border border-hairline ${
        showFallback ? 'bg-elevated' : 'bg-page'
      } ${SIZE_CLASS[size]}`}
    >
      {showFallback ? (
        // bg-elevated (one tier lighter than surface) + text-ink, not
        // bg-page + text-muted -- a company with no real logo art was
        // reading as "disabled" next to companies with real, colorful
        // logos, purely from the near-zero contrast of the old fallback.
        <span className="font-data font-semibold text-ink" aria-hidden="true">
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
