import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import VolRangeV4 from './VolRangeV4';

const range = {
  level: 'COMPANY' as const,
  n_events: 14,
  min_excess_move_pct: -3.2,
  median_excess_move_pct: 0.4,
  max_excess_move_pct: 4.1,
  as_of: '2026-07-31',
};

describe('VolRangeV4', () => {
  it('draws the band, median and scale numerals', () => {
    render(<VolRangeV4 range={range} />);
    expect(screen.getByText('−3.2%')).toBeInTheDocument();
    expect(screen.getByText('median +0.4%')).toBeInTheDocument();
    expect(screen.getByText('+4.1%')).toBeInTheDocument();
    expect(screen.getByText('14 measured events · as of 2026-07-31')).toBeInTheDocument();
  });

  it('pins the actual move inside the band without the outside note', () => {
    render(<VolRangeV4 range={range} move={1.9} />);
    expect(screen.getByText('this move +1.9%')).toBeInTheDocument();
    expect(screen.queryByText('outside the usual band')).not.toBeInTheDocument();
  });

  it('stretches the scale and says so when the move is outside the band', () => {
    render(<VolRangeV4 range={range} move={-6.5} />);
    expect(screen.getByText('this move −6.5%')).toBeInTheDocument();
    expect(screen.getByText('outside the usual band')).toBeInTheDocument();
  });

  it('labels pooled sector-level samples honestly', () => {
    render(<VolRangeV4 range={{ ...range, level: 'SECTOR' }} />);
    expect(screen.getByText('sector-level · 14 measured events · as of 2026-07-31')).toBeInTheDocument();
  });
});
