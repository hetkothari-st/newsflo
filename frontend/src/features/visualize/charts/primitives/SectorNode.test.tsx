import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SectorNode from './SectorNode';

describe('SectorNode', () => {
  it('shows the sector label and count', () => {
    render(<SectorNode sector="defense" count={3} />);
    expect(screen.getByText('Defense')).toBeInTheDocument();
    expect(screen.getByText('(3)')).toBeInTheDocument();
  });

  it('omits the count when not provided', () => {
    render(<SectorNode sector="metals" />);
    expect(screen.getByText('Metals')).toBeInTheDocument();
    expect(screen.queryByText(/\(/)).not.toBeInTheDocument();
  });
});
