import { useState } from 'react';

function initials(ticker: string): string {
  const base = ticker.split('.')[0];
  return base.slice(0, 2).toUpperCase();
}

const SIZE_CLASS = {
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
  size?: 'md' | 'lg';
}) {
  const [failed, setFailed] = useState(false);
  const showFallback = !logoUrl || failed;

  return (
    <span
      className={`flex shrink-0 items-center justify-center overflow-hidden border border-hairline bg-page ${SIZE_CLASS[size]}`}
    >
      {showFallback ? (
        <span className="font-data text-muted" aria-hidden="true">
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
