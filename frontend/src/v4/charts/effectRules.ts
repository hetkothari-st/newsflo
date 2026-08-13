/* The ONE up/down/flat rule for the charts deck.

   Final-review finding I9: this rule existed twice, and the two copies
   disagreed. chartComponents.tsx's `effectClass` required a measured move
   (`excess_move_pct == null` -> 'flat'); chartsData.ts's `rowEffectSign`,
   which decides whether the Winners/Losers tile is even OFFERED, had no
   such guard. On an exposure-only story (rows with a real economic_effect
   but no measured move) availability said "show the split chart" and the
   bucketing then put every row in neutral -- the deck rendered
   "Positive impact · 0 / Negative impact · 0", two empty columns. That is
   precisely the empty state the app-wide hide-no-data rule forbids.

   This is a LEAF module on purpose: it imports NOTHING -- not even the
   ChartRow type -- and takes the three fields it reads structurally.
   That is what lets both chartsData.ts and chartComponents.tsx import it
   without recreating the import cycle the two copies were duplicated to
   avoid in the first place. Any ChartRow satisfies EffectRow. */
export interface EffectRow {
  excess_move_pct: number | null;
  economic_effect?: string | null;
  direction: string;
}

export type EffectClass = 'up' | 'down' | 'flat';

/* Per-row bucket key. A measured move is required first: a row with no
   excess_move_pct has no observed reaction to place on a winners/losers
   axis at all, so it is 'flat' (rendered as exposure-only), never a
   winner or a loser on the strength of a fundamental verdict alone.
   Beyond that the gate's `economic_effect` is authoritative and the
   legacy AlertCompany.direction is the fallback ONLY for pre-gate rows
   that carry no economic_effect at all. */
export function effectClass(row: EffectRow): EffectClass {
  if (row.excess_move_pct == null) return 'flat';
  if (row.economic_effect) {
    if (row.economic_effect === 'positive') return 'up';
    if (row.economic_effect === 'negative') return 'down';
    return 'flat';
  }
  if (row.direction === 'bullish') return 'up';
  if (row.direction === 'bearish') return 'down';
  return 'flat';
}
