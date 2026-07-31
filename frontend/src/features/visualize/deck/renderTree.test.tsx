import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import type { AlertCompany } from '../../../lib/api';
import CompanyNode from '../charts/primitives/CompanyNode';
import { renderTree } from './renderTree';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50', sector: 'banking',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'why', key_points: [],
    basis: 'direct_mention', confidence: 'llm_estimate', confidence_score: 60,
    time_horizon: 'Short-Term', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

const companies = [
  company({ company_id: 1, ticker: 'HDFCBANK', name: 'HDFC Bank', direction: 'bearish' }),
  company({ company_id: 2, ticker: 'DLF', name: 'DLF', direction: 'bearish' }),
];

function tree(onClick?: (id: number) => void) {
  return renderTree(
    {
      newsLabel: 'News · 22 Jul',
      newsHeadline: 'RBI raises repo rate 25 bps',
      levels: [
        { key: 'direct', label: 'Primary', sub: 'directly affected', companyIds: [1] },
        { key: 'indirect_l1', label: 'Secondary', sub: 'indirect', companyIds: [2] },
        // Empty and unresolvable levels must be omitted, not rendered blank.
        { key: 'indirect_l2', label: 'Tertiary', sub: 'wider ecosystem', companyIds: [999] },
      ],
      nodeContent: (c) => (
        <CompanyNode name={c.name} ticker={c.ticker} direction={c.direction} onClick={onClick ? () => onClick(c.company_id) : undefined} />
      ),
    },
    companies,
  );
}

describe('renderTree (Doc-1 §3)', () => {
  it('renders a real SVG diagram with connector edges, not a styled list', () => {
    const { container } = render(tree());
    expect(container.querySelector('svg.deck-tree')).not.toBeNull();
    expect(container.querySelectorAll('path.deck-edge').length).toBeGreaterThanOrEqual(3);
  });

  it('renders the news root and each level band label with its tspan sub', () => {
    const { container } = render(tree());
    expect(screen.getByText('RBI raises repo rate 25 bps')).toBeInTheDocument();
    expect(screen.getByText('Primary')).toBeInTheDocument();
    const sub = container.querySelector('tspan.deck-bandsub');
    expect(sub?.textContent).toBe('directly affected');
    expect(sub?.getAttribute('dx')).toBe('12');
  });

  it('renders company nodes via foreignObject and omits unresolvable levels', () => {
    const { container } = render(tree());
    expect(screen.getByText('HDFCBANK')).toBeInTheDocument();
    // 'DLF' appears as both name and ticker on the same node face.
    expect(screen.getAllByText('DLF').length).toBeGreaterThanOrEqual(1);
    // Level whose only id has no backing row is dropped entirely.
    expect(screen.queryByText('Tertiary')).toBeNull();
    // news + 2 company nodes
    expect(container.querySelectorAll('foreignObject').length).toBe(3);
  });

  it('nodes are tappable through the provided nodeContent', async () => {
    const onClick = vi.fn();
    render(tree(onClick));
    await userEvent.click(screen.getByText('HDFCBANK'));
    expect(onClick).toHaveBeenCalledWith(1);
  });
});
