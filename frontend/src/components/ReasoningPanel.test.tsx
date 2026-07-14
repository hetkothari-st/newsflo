import { render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import ReasoningPanel, { precedentLine, splitRationaleIntoPoints } from './ReasoningPanel';
import type { AlertCompany } from '../lib/api';
import { LanguageProvider } from '../lib/language';

function render(ui: ReactElement) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>{ui}</LanguageProvider>
    </MemoryRouter>,
  );
}

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
  past_mentions: [],
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

  it('shows past mentions as links when present', () => {
    const withHistory = {
      ...base,
      past_mentions: [
        {
          alert_id: 5, article_title: 'HDFC raises EMI cap on personal loans',
          article_url: 'https://example.com/hdfc-emi', created_at: '2026-05-01T00:00:00+00:00',
          direction: 'bearish', category: 'banking',
        },
      ],
    };
    render(<ReasoningPanel company={withHistory} />);
    expect(screen.getByText('Previously')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /HDFC raises EMI cap on personal loans/ });
    expect(link).toHaveAttribute('href', 'https://example.com/hdfc-emi');
  });

  it('omits the Previously section when there is no history', () => {
    render(<ReasoningPanel company={base} />);
    expect(screen.queryByText('Previously')).not.toBeInTheDocument();
  });

  it('links to the company detail page for an Indian company', () => {
    render(<ReasoningPanel company={base} />);
    const link = screen.getByRole('link', { name: /view full details/i });
    expect(link).toHaveAttribute('href', '/company/1');
  });

  it('omits the detail-page link for a global company', () => {
    render(<ReasoningPanel company={{ ...base, market: 'GLOBAL' }} />);
    expect(screen.queryByRole('link', { name: /view full details/i })).not.toBeInTheDocument();
  });
});
