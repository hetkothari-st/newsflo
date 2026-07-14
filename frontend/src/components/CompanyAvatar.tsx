// No verified per-company domain/logo exists in the data model — guessing a
// domain from the ticker risks rendering a different company's real brand
// mark (e.g. "reliance.com" belongs to a US steel company, not Reliance
// Industries). A deterministic monogram is the honest stand-in: same ticker
// always resolves to the same initials + color, no network fetch, no risk of
// a wrong logo. Swap in a real <img src={logo_url}> here if the backend ever
// adds a verified logo field.
const AVATAR_PALETTE = [
  '#F5A623', // amber
  '#4A90D9', // blue
  '#2DD4BF', // teal
  '#E85D4C', // red-orange
  '#9B7EDE', // violet
  '#5FB878', // green
  '#D4708C', // rose
  '#6C8CD5', // indigo
];

function avatarColor(ticker: string): string {
  let hash = 0;
  for (let i = 0; i < ticker.length; i++) hash = (hash * 31 + ticker.charCodeAt(i)) >>> 0;
  return AVATAR_PALETTE[hash % AVATAR_PALETTE.length];
}

function initials(ticker: string): string {
  const base = ticker.split('.')[0];
  return base.slice(0, 2).toUpperCase();
}

export default function CompanyAvatar({ ticker, size = 'md' }: { ticker: string; size?: 'md' | 'lg' }) {
  const sizeClass = size === 'lg' ? 'h-14 w-14 text-base' : 'h-9 w-9 text-xs';
  return (
    <span
      aria-hidden="true"
      className={`flex shrink-0 items-center justify-center rounded-lg font-bold text-page ${sizeClass}`}
      style={{ backgroundColor: avatarColor(ticker) }}
    >
      {initials(ticker)}
    </span>
  );
}
