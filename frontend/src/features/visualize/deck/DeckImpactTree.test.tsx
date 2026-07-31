import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { LanguageProvider } from '../../../lib/language';
import DeckImpactTree from './DeckImpactTree';
import DeckLevelTree from './DeckLevelTree';
import { article, company, createdAt, fullCompanies, sparseCompanies } from './fixtures';

function render(ui: ReactElement) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>{ui}</LanguageProvider>
    </MemoryRouter>,
  );
}

describe('DeckImpactTree (chart 1)', () => {
  it('renders a branching SVG with edges for the sparse one-per-level alert', () => {
    const { container } = render(
      <DeckImpactTree companies={sparseCompanies} article={article} alertCreatedAt={createdAt} />,
    );
    expect(container.querySelector('svg.deck-tree')).not.toBeNull();
    expect(container.querySelectorAll('path.deck-edge').length).toBeGreaterThan(4);
    expect(screen.getByText('Primary')).toBeInTheDocument();
    expect(screen.getByText('Secondary')).toBeInTheDocument();
    expect(screen.getByText('Tertiary')).toBeInTheDocument();
  });

  it('renders all 9 companies of the full alert', () => {
    render(<DeckImpactTree companies={fullCompanies} article={article} alertCreatedAt={createdAt} />);
    for (const c of fullCompanies) {
      // getAllByText: a ticker like DLF also appears as the node's name line.
      expect(screen.getAllByText(c.ticker).length).toBeGreaterThanOrEqual(1);
    }
  });

  it('omits empty levels entirely', () => {
    render(
      <DeckImpactTree
        companies={[company({ company_id: 1, ticker: 'HDFCBANK', impact_level: 'direct' })]}
        article={article}
        alertCreatedAt={createdAt}
      />,
    );
    expect(screen.getByText('Primary')).toBeInTheDocument();
    expect(screen.queryByText('Secondary')).toBeNull();
    expect(screen.queryByText('Tertiary')).toBeNull();
  });

  it('shows the measured move when present and glyph-only when absent (Doc-1 §2)', () => {
    render(<DeckImpactTree companies={sparseCompanies} article={article} alertCreatedAt={createdAt} />);
    // HDFCBANK has excess_move_pct -1.4; BAJFINANCE has magnitude but no
    // measurement -> its node face must NOT show any percentage.
    expect(screen.getByText(/-1\.4%/)).toBeInTheDocument();
    const bajNode = screen.getByText('BAJFINANCE').closest('button');
    expect(bajNode?.textContent).not.toMatch(/%/);
  });

  it('opens the reasoning drawer on tap', async () => {
    render(<DeckImpactTree companies={sparseCompanies} article={article} alertCreatedAt={createdAt} />);
    await userEvent.click(screen.getByText('HDFCBANK'));
    expect(screen.getByText(/rates bite here/)).toBeInTheDocument();
  });

  it('has a Positive/Negative legend', () => {
    render(<DeckImpactTree companies={sparseCompanies} article={article} alertCreatedAt={createdAt} />);
    expect(screen.getByText('Positive')).toBeInTheDocument();
    expect(screen.getByText('Negative')).toBeInTheDocument();
  });
});

describe('DeckLevelTree (chart 4)', () => {
  it('labels each band with an explicit level number and count', () => {
    const { container } = render(
      <DeckLevelTree companies={fullCompanies} article={article} alertCreatedAt={createdAt} />,
    );
    expect(screen.getByText('Level 1')).toBeInTheDocument();
    expect(screen.getByText('Level 2')).toBeInTheDocument();
    expect(screen.getByText('Level 3')).toBeInTheDocument();
    const subs = [...container.querySelectorAll('tspan.deck-bandsub')].map((t) => t.textContent);
    expect(subs).toEqual(['direct · 3', 'indirect · 3', 'ecosystem · 3']);
  });

  it('orders children under their parent (caused-by reading)', () => {
    const { container } = render(
      <DeckLevelTree companies={fullCompanies} article={article} alertCreatedAt={createdAt} />,
    );
    // Level 2: BAJFINANCE (parent 1) and MARUTI (parent 1) group before DLF
    // (parent 2), because parent 1 precedes parent 2 in level 1's order.
    const tickers = [...container.querySelectorAll('foreignObject .font-data')].map((e) => e.textContent);
    const l2 = ['BAJFINANCE', 'MARUTI', 'DLF'].map((t) => tickers.indexOf(t));
    expect(l2[0]).toBeLessThan(l2[1]);
    expect(l2[1]).toBeLessThan(l2[2]);
  });

  it('renders a real diagram with edges on sparse data', () => {
    const { container } = render(
      <DeckLevelTree companies={sparseCompanies} article={article} alertCreatedAt={createdAt} />,
    );
    expect(container.querySelectorAll('path.deck-edge').length).toBeGreaterThan(4);
  });
});
