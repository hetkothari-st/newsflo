/* Company logo for the broadsheet UI. Resolution (candidate chain,
   transparent-placeholder probe, per-ticker cache) lives in
   logoResolve.ts and is shared with the SVG charts, so a company shows
   the SAME mark -- or the same initials fallback -- everywhere. */
import { useLogo } from './logoResolve';

function initials(ticker: string): string {
  return ticker.split('.')[0].slice(0, 2).toUpperCase();
}

export default function LogoV4({
  logoUrl,
  ticker,
  name,
  size = 'sm',
}: {
  logoUrl?: string | null;
  ticker: string;
  name?: string;
  size?: 'sm' | 'md';
}) {
  const resolved = useLogo(logoUrl, ticker, name);
  const showFallback = resolved === null;
  return (
    <span className={`clg clg-${size} ${showFallback ? 'clg-fb' : ''}`} data-testid={`v4logo-${ticker}`}>
      {showFallback ? (
        <span aria-hidden="true">{initials(ticker)}</span>
      ) : resolved !== undefined ? (
        <img src={resolved} alt="" loading="lazy" />
      ) : null}
    </span>
  );
}
