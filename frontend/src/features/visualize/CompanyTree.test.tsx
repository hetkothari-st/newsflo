import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CompanyTree from './CompanyTree';
import type { AlertCompany } from '../../lib/api';
import { groupByImpact } from './transforms';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'Refiner up.',
    key_points: [], basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
    in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

describe('CompanyTree', () => {
  const companies = [
    company({ company_id: 1, ticker: 'AAA.NS', name: 'Alpha Co', direction: 'bullish' }),
    company({ company_id: 2, ticker: 'BBB.NS', name: 'Beta Co', direction: 'bearish' }),
  ];
  const groups = groupByImpact(companies);

  it('renders the root label and one branch per group', () => {
    render(<CompanyTree articleTitle="Some event" groups={groups} groupMode="impact" />);
    expect(screen.getByText('Some event')).toBeInTheDocument();
    expect(screen.getByText(/Bullish · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Bearish · 1/)).toBeInTheDocument();
  });

  it('labels the tree with the article title and the active group mode', () => {
    render(<CompanyTree articleTitle="Some event" groups={groups} groupMode="impact" />);
    expect(screen.getByRole('group', { name: 'Some event impact tree' })).toBeInTheDocument();
  });

  it('renders one leaf per company with its ticker', () => {
    render(<CompanyTree articleTitle="Some event" groups={groups} groupMode="impact" />);
    expect(screen.getByText('AAA')).toBeInTheDocument();
    expect(screen.getByText('BBB')).toBeInTheDocument();
  });

  it('reveals the reasoning panel for a company when its leaf is clicked', () => {
    render(<CompanyTree articleTitle="Some event" groups={groups} groupMode="impact" />);
    fireEvent.click(screen.getByRole('button', { name: /Alpha Co \(AAA.NS\)/ }));
    expect(screen.getByText('Refiner up.')).toBeInTheDocument();
  });

  it('reveals the reasoning panel when a leaf is activated with the keyboard', () => {
    render(<CompanyTree articleTitle="Some event" groups={groups} groupMode="impact" />);
    fireEvent.keyDown(screen.getByRole('button', { name: /Beta Co \(BBB.NS\)/ }), { key: 'Enter' });
    expect(screen.getByText('Refiner up.')).toBeInTheDocument();
  });

  it('truncates a long article title rather than overflowing', () => {
    const longTitle = 'A'.repeat(80);
    render(<CompanyTree articleTitle={longTitle} groups={groups} groupMode="impact" />);
    expect(screen.queryByText(longTitle)).not.toBeInTheDocument();
    expect(screen.getByText(/…$/)).toBeInTheDocument();
  });
});
