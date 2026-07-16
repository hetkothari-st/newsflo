import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
  confidence_score: 50,
  time_horizon: 'Short-Term',
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

describe('ReasoningPanel evidence section', () => {
  const withEvidence: AlertCompany = {
    ...base,
    confidence_band: 'HIGH',
    reasons: ['Refining margins widen on crude spike.'],
    evidence_refs: ['RULE_CRUDE_OIL_UP', 'article: crude jumped 8% overnight'],
    risks: ['Margin reversal if crude falls back.'],
    assumptions: ['Crude stays elevated for the quarter.'],
    unknowns: ['Whether this is a durable shock or a spike.'],
    alternative_hypothesis: 'Market has already priced this in.',
    confidence_contributors: ['Matched a known rulebook rule'],
    confidence_penalties: ['No historical calibration yet'],
  };

  it('renders no evidence section and no confidence badge for a legacy alert (reasons empty)', () => {
    render(<ReasoningPanel company={base} />);
    expect(screen.queryByText('Why this call')).not.toBeInTheDocument();
    expect(screen.queryByText('High')).not.toBeInTheDocument();
  });

  it('renders the confidence band badge when confidence_band is set', () => {
    render(<ReasoningPanel company={withEvidence} />);
    expect(screen.getByText('High')).toBeInTheDocument();
  });

  it('shows a "Why this call" toggle that is collapsed by default', () => {
    render(<ReasoningPanel company={withEvidence} />);
    expect(screen.getByText('Why this call')).toBeInTheDocument();
    expect(screen.queryByText('Refining margins widen on crude spike.')).not.toBeInTheDocument();
  });

  it('expands to show reasons, evidence, alternative view, risks, and confidence breakdown', async () => {
    render(<ReasoningPanel company={withEvidence} />);
    await userEvent.click(screen.getByRole('button', { name: 'Why this call' }));

    expect(screen.getByText('Refining margins widen on crude spike.')).toBeInTheDocument();
    expect(screen.getByText('Crude oil up')).toBeInTheDocument(); // RULE_CRUDE_OIL_UP label
    expect(screen.getByText('crude jumped 8% overnight')).toBeInTheDocument(); // article: prefix stripped
    expect(screen.getByText('Market has already priced this in.')).toBeInTheDocument();
    expect(screen.getByText('Margin reversal if crude falls back.')).toBeInTheDocument();
    expect(screen.getByText('Crude stays elevated for the quarter.')).toBeInTheDocument();
    expect(screen.getByText('Whether this is a durable shock or a spike.')).toBeInTheDocument();
    expect(screen.getByText('Matched a known rulebook rule')).toBeInTheDocument();
    expect(screen.getByText('No historical calibration yet')).toBeInTheDocument();
  });

  it('shows the event type line when eventType is passed', async () => {
    render(<ReasoningPanel company={withEvidence} eventType="crude_oil" />);
    await userEvent.click(screen.getByRole('button', { name: 'Why this call' }));
    expect(screen.getByText('Event: Crude oil')).toBeInTheDocument();
  });

  it('omits the event type line when eventType is not passed', async () => {
    render(<ReasoningPanel company={withEvidence} />);
    await userEvent.click(screen.getByRole('button', { name: 'Why this call' }));
    expect(screen.queryByText(/^Event:/)).not.toBeInTheDocument();
  });

  it('omits the alternative view line when alternative_hypothesis is null', async () => {
    render(<ReasoningPanel company={{ ...withEvidence, alternative_hypothesis: null }} eventType={null} />);
    await userEvent.click(screen.getByRole('button', { name: 'Why this call' }));
    expect(screen.queryByText('Alternative view')).not.toBeInTheDocument();
  });

  it('visually distinguishes evidence by provenance: rule as a tag, article/historical with a superscript label, other plain', async () => {
    const withMixedEvidence = {
      ...withEvidence,
      evidence_refs: [
        'RULE_CRUDE_OIL_UP',
        'article: crude jumped 8% overnight',
        'historical: 2018 sanctions episode',
        'a plain unprefixed evidence string',
      ],
    };
    render(<ReasoningPanel company={withMixedEvidence} />);
    await userEvent.click(screen.getByRole('button', { name: 'Why this call' }));

    // Rule evidence renders its label inside a small muted tag <span>, not
    // as bare text alongside the bullet -- distinguishing it visually from
    // the other list items.
    const ruleTag = screen.getByText('Crude oil up');
    expect(ruleTag.tagName).toBe('SPAN');
    expect(ruleTag.className).toContain('rounded-full');

    // Article evidence gets a superscript "Article" label preceding the text.
    const articleLabel = screen.getByText('Article');
    expect(articleLabel.tagName).toBe('SUP');
    expect(screen.getByText('crude jumped 8% overnight')).toBeInTheDocument();

    // Historical evidence gets a superscript "Historical" label.
    const historicalLabel = screen.getByText('Historical');
    expect(historicalLabel.tagName).toBe('SUP');
    expect(screen.getByText('2018 sanctions episode')).toBeInTheDocument();

    // A plain/other-kind evidence ref shows neither a rule tag nor a
    // provenance label -- just its own text.
    const plainItem = screen.getByText('a plain unprefixed evidence string');
    expect(plainItem.tagName).toBe('LI');
    expect(screen.queryAllByText('Article')).toHaveLength(1); // only the one above
    expect(screen.queryAllByText('Historical')).toHaveLength(1); // only the one above
  });
});
