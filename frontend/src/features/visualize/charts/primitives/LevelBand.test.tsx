import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import LevelBand from './LevelBand';

describe('LevelBand', () => {
  it('renders the label and children with a single child (sparse-data case)', () => {
    render(
      <LevelBand label="Level 1 (Direct Impact)">
        <span>only-node</span>
      </LevelBand>,
    );
    expect(screen.getByText('Level 1 (Direct Impact)')).toBeInTheDocument();
    expect(screen.getByText('only-node')).toBeInTheDocument();
  });

  it('renders every child with eight nodes', () => {
    render(
      <LevelBand label="Level 1 (Direct Impact)">
        {Array.from({ length: 8 }, (_, i) => (
          <span key={i}>{`node-${i}`}</span>
        ))}
      </LevelBand>,
    );
    for (let i = 0; i < 8; i += 1) {
      expect(screen.getByText(`node-${i}`)).toBeInTheDocument();
    }
  });
});
