import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ReasoningPanel, { precedentLine, splitRationaleIntoPoints } from './ReasoningPanel';
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
  key_points: [],
  basis: 'direct_mention',
  confidence: 'llm_estimate',
  market: 'IN',
  in_my_holdings: false,
};

describe('precedentLine', () => {
  it('cites the blended range as historical precedent when calibrated', () => {
    const line = precedentLine({ ...base, confidence: 'calibrated' });
    expect(line).toMatch(/historical precedent/i);
    expect(line).toContain('comparable bullish move');
  });
  it('notes the model estimate when not calibrated', () => {
    expect(precedentLine(base)).toMatch(/model's own estimate/i);
  });
});

describe('splitRationaleIntoPoints', () => {
  it('splits a multi-sentence rationale into one point per sentence', () => {
    const rationale =
      'State Bank of India is the parent of SBI Funds Management. ' +
      'For a bank of SBI size, the direct earnings impact is modest. ' +
      'Historical precedent: PSU bank holding-company premiums expand when subsidiaries list.';
    const points = splitRationaleIntoPoints(rationale);
    expect(points).toEqual([
      'State Bank of India is the parent of SBI Funds Management.',
      'For a bank of SBI size, the direct earnings impact is modest.',
      'Historical precedent: PSU bank holding-company premiums expand when subsidiaries list.',
    ]);
  });

  it('does not split on a decimal number or mid-sentence abbreviation', () => {
    const rationale = 'Revenue grew 2.5x amid strong e.g. demand from exports.';
    expect(splitRationaleIntoPoints(rationale)).toEqual([rationale]);
  });

  it('returns a single point for a single-sentence rationale', () => {
    expect(splitRationaleIntoPoints('Margins up.')).toEqual(['Margins up.']);
  });
});

describe('ReasoningPanel', () => {
  it('renders the company, ticker and rationale', () => {
    render(<ReasoningPanel company={base} />);
    expect(screen.getByText(/RELIANCE\.NS/)).toBeInTheDocument();
    expect(screen.getByText('Margins up.')).toBeInTheDocument();
  });

  it('renders a multi-sentence rationale as separate bullet points when key_points is empty', () => {
    const multiSentence = {
      ...base,
      rationale: 'First reason applies here. Second reason applies too.',
    };
    render(<ReasoningPanel company={multiSentence} />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('First reason applies here.');
    expect(items[1]).toHaveTextContent('Second reason applies too.');
  });

  it('prefers key_points over the full rationale when present', () => {
    const withKeyPoints = {
      ...base,
      rationale: 'A long paragraph nobody wants to read in full on a feed card.',
      key_points: ['Crude eases, margins widen', '2018 sanctions precedent: GRM +$2/bbl'],
    };
    render(<ReasoningPanel company={withKeyPoints} />);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('Crude eases, margins widen');
    expect(items[1]).toHaveTextContent('2018 sanctions precedent: GRM +$2/bbl');
    expect(screen.queryByText(/A long paragraph/)).not.toBeInTheDocument();
  });
});
