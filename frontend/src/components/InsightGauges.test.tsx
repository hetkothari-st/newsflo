import { render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import InsightGauges from './InsightGauges';
import { LanguageProvider } from '../lib/language';

function render(ui: ReactElement) {
  return rtlRender(<LanguageProvider>{ui}</LanguageProvider>);
}

describe('InsightGauges', () => {
  it('shows the confidence percentage and filled dot count', () => {
    render(<InsightGauges confidenceScore={84} timeHorizon="Short-Term" impactLevel="direct" />);
    expect(screen.getByText('84%')).toBeInTheDocument();
    expect(screen.getAllByTestId('confidence-dot-filled')).toHaveLength(4);
  });

  it('shows the horizon label and glyph', () => {
    render(<InsightGauges confidenceScore={50} timeHorizon="Medium-Term" impactLevel="direct" />);
    expect(screen.getByText('Medium')).toBeInTheDocument();
    expect(screen.getByText('◑')).toBeInTheDocument();
  });

  it('shows the impact label', () => {
    render(<InsightGauges confidenceScore={50} timeHorizon="Short-Term" impactLevel="indirect_l1" />);
    expect(screen.getByText('Indirect')).toBeInTheDocument();
  });

  it('defaults impact to Direct when impactLevel is undefined', () => {
    render(<InsightGauges confidenceScore={50} timeHorizon="Short-Term" impactLevel={undefined} />);
    expect(screen.getByText('Direct')).toBeInTheDocument();
  });

  it('labels all three columns', () => {
    render(<InsightGauges confidenceScore={50} timeHorizon="Short-Term" impactLevel="direct" />);
    expect(screen.getByText('Confidence')).toBeInTheDocument();
    expect(screen.getByText('Horizon')).toBeInTheDocument();
    expect(screen.getByText('Impact')).toBeInTheDocument();
  });
});
