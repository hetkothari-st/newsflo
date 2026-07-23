import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import IntensityBreakdownPopup from './IntensityBreakdownPopup';
import type { Intensity } from '../../lib/feedV2Api';

function makeIntensity(overrides: Partial<Intensity> = {}): Intensity {
  return {
    score: 82,
    band: 'High',
    components: [
      { label: 'excess', raw: -4.2, weight: 0.55, contribution: 55.0 },
      { label: 'volume', raw: 3.1, weight: 0.25, contribution: 25.0 },
      { label: 'breadth', raw: 40, weight: 0.2, contribution: 8.0 },
    ],
    ...overrides,
  };
}

describe('IntensityBreakdownPopup', () => {
  it('renders the large score and band label', () => {
    render(<IntensityBreakdownPopup intensity={makeIntensity()} />);
    expect(screen.getByText('82')).toBeInTheDocument();
    expect(screen.getByText('High')).toBeInTheDocument();
  });

  it('renders one row per component with label, raw, and weight', () => {
    render(<IntensityBreakdownPopup intensity={makeIntensity()} />);
    expect(screen.getByText(/excess/i)).toBeInTheDocument();
    expect(screen.getByText(/-4\.2/)).toBeInTheDocument();
    expect(screen.getByText(/×0\.55/)).toBeInTheDocument();
    expect(screen.getByText(/volume/i)).toBeInTheDocument();
    expect(screen.getByText(/breadth/i)).toBeInTheDocument();
  });

  it('always renders the exact compliance disclaimer', () => {
    render(<IntensityBreakdownPopup intensity={makeIntensity()} />);
    expect(
      screen.getByText(
        "Intensity measures how hard the news hit this stock — not whether it's a good investment.",
      ),
    ).toBeInTheDocument();
  });

  it('renders the disclaimer for every band, not just High', () => {
    const { rerender } = render(<IntensityBreakdownPopup intensity={makeIntensity({ band: 'Low', score: 12 })} />);
    expect(
      screen.getByText(
        "Intensity measures how hard the news hit this stock — not whether it's a good investment.",
      ),
    ).toBeInTheDocument();

    rerender(<IntensityBreakdownPopup intensity={makeIntensity({ band: 'Moderate', score: 55 })} />);
    expect(
      screen.getByText(
        "Intensity measures how hard the news hit this stock — not whether it's a good investment.",
      ),
    ).toBeInTheDocument();
  });

  it('handles a component with zero weight without dividing by zero', () => {
    const intensity = makeIntensity({
      components: [{ label: 'excess', raw: 0, weight: 0, contribution: 0 }],
    });
    render(<IntensityBreakdownPopup intensity={intensity} />);
    expect(screen.getByText(/excess/i)).toBeInTheDocument();
  });
});
