/* Company logo for the broadsheet UI: the same Brandfetch art the
   deployed shell uses (row.logo_url from the backend), rendered
   monochrome to stay inside the paper/ink identity. Falls back to
   ink-on-paper ticker initials -- a company without logo art must still
   read as a real company, never a broken image. */
import { useState } from 'react';

function initials(ticker: string): string {
  return ticker.split('.')[0].slice(0, 2).toUpperCase();
}

export default function LogoV4({
  logoUrl,
  ticker,
  size = 'sm',
}: {
  logoUrl?: string | null;
  ticker: string;
  size?: 'sm' | 'md';
}) {
  const [failed, setFailed] = useState(false);
  const showFallback = !logoUrl || failed;
  return (
    <span className={`clg clg-${size} ${showFallback ? 'clg-fb' : ''}`} data-testid={`v4logo-${ticker}`}>
      {showFallback ? (
        <span aria-hidden="true">{initials(ticker)}</span>
      ) : (
        <img src={logoUrl ?? undefined} alt="" loading="lazy" onError={() => setFailed(true)} />
      )}
    </span>
  );
}
