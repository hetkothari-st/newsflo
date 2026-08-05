import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import VolatilityRange from './VolatilityRange';

const range = {
  level: 'COMPANY' as const,
  n_events: 9,
  min_excess_move_pct: -1.8,
  median_excess_move_pct: 0.6,
  max_excess_move_pct: 2.4,
  as_of: '2026-08-05',
};

describe('VolatilityRange', () => {
  it('renders the measured range with its sample count', () => {
    render(<VolatilityRange range={range} />);
    expect(screen.getByText(/−1\.8%/)).toBeInTheDocument();
    expect(screen.getByText(/\+2\.4%/)).toBeInTheDocument();
    expect(screen.getByText(/9 events/)).toBeInTheDocument();
    expect(screen.queryByText(/sector-level/)).not.toBeInTheDocument();
  });

  it('labels a pooled sector range so it is never read as stock-specific', () => {
    render(<VolatilityRange range={{ ...range, level: 'SECTOR', n_events: 12 }} />);
    expect(screen.getByText(/sector-level/)).toBeInTheDocument();
    expect(screen.getByText(/12 events/)).toBeInTheDocument();
  });

  it('renders nothing without a range', () => {
    const { container } = render(<VolatilityRange range={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
