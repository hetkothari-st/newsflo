import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ReasoningPanel, { precedentLine } from './ReasoningPanel';
import type { AlertCompany } from '../lib/api';

const base: AlertCompany = {
  company_id: 1,
  ticker: 'RELIANCE.NS',
  name: 'Reliance',
  index_tier: 'NIFTY50',
  direction: 'bullish',
  magnitude_low: 2,
  magnitude_high: 4,
  rationale: 'Margins up.',
  basis: 'direct_mention',
  confidence: 'llm_estimate',
  market: 'IN',
  in_my_holdings: false,
};

describe('precedentLine', () => {
  it('cites the blended range as historical precedent when calibrated', () => {
    const line = precedentLine({ ...base, confidence: 'calibrated' });
    expect(line).toMatch(/historical precedent/i);
    expect(line).toContain('+2.0% to +4.0%');
  });
  it('notes the model estimate when not calibrated', () => {
    expect(precedentLine(base)).toMatch(/model's own estimate/i);
  });
});

describe('ReasoningPanel', () => {
  it('renders the company, ticker and rationale', () => {
    render(<ReasoningPanel company={base} />);
    expect(screen.getByText(/RELIANCE\.NS/)).toBeInTheDocument();
    expect(screen.getByText('Margins up.')).toBeInTheDocument();
  });
});
