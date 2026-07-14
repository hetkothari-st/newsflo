export default function DirectionArrow({ direction }: { direction: string }) {
  const bullish = direction === 'bullish';
  return (
    <span className={bullish ? 'text-bullish' : 'text-bearish'} aria-hidden="true">
      {bullish ? '▲' : '▼'}
    </span>
  );
}
