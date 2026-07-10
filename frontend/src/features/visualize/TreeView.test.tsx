import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import TreeView from './TreeView';
import { buildImpactTree } from './transforms';
import type { AlertCompany } from '../../lib/api';

const companies: AlertCompany[] = [
  {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50', direction: 'bullish',
    magnitude_low: 1, magnitude_high: 2, rationale: 'Refiner up.', basis: 'direct_mention',
    confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, sector: 'Energy',
  },
];

describe('TreeView', () => {
  it('renders the tree built by the given build function', () => {
    render(<TreeView articleTitle="Some event" companies={companies} build={buildImpactTree} />);
    expect(screen.getByText('Some event')).toBeInTheDocument();
    expect(screen.getByText('Alpha Co')).toBeInTheDocument();
  });

  it('shows the reasoning panel for a company after clicking its leaf', () => {
    render(<TreeView articleTitle="Some event" companies={companies} build={buildImpactTree} />);
    fireEvent.click(screen.getByText('Alpha Co'));
    expect(screen.getByText('Refiner up.')).toBeInTheDocument();
  });
});
