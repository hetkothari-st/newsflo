import { render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { LanguageProvider } from '../../../lib/language';
import DeckSplit from './DeckSplit';
import DeckTimeline from './DeckTimeline';
import DeckSectors from './DeckSectors';
import { article, company, createdAt, fullCompanies, sparseCompanies } from './fixtures';

function render(ui: ReactElement) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>{ui}</LanguageProvider>
    </MemoryRouter>,
  );
}

describe('DeckSplit (chart 6)', () => {
  it('always renders both direction panels, with — for an empty side', () => {
    // Sparse fixture is all-bearish: Positive panel must still render.
    render(<DeckSplit companies={sparseCompanies} article={article} alertCreatedAt={createdAt} />);
    expect(screen.getByText('Positive')).toBeInTheDocument();
    expect(screen.getByText('Negative')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('splits bullish from bearish and ranks by |measured move|', () => {
    const { container } = render(
      <DeckSplit companies={fullCompanies} article={article} alertCreatedAt={createdAt} />,
    );
    const panels = [...container.querySelectorAll('.deck-splitpanel')];
    expect(panels).toHaveLength(2); // no neutral companies in the fixture
    const positiveTickers = [...panels[0].querySelectorAll('.font-data')].map((e) => e.textContent);
    expect(positiveTickers).toContain('HINDUNILVR');
    expect(positiveTickers).not.toContain('HDFCBANK');
    // Bearish ranked by |move| desc: BAJFINANCE -2.1 first.
    const negativeTickers = [...panels[1].querySelectorAll('.font-data')].map((e) => e.textContent ?? '');
    expect(negativeTickers.find((t) => /^[A-Z]+$/.test(t))).toBe('BAJFINANCE');
  });

  it('renders a neutral panel only when neutral companies exist', () => {
    render(
      <DeckSplit
        companies={[company({ company_id: 50, ticker: 'ZEE', direction: 'neutral' })]}
        article={article}
        alertCreatedAt={createdAt}
      />,
    );
    expect(screen.getByText('No significant impact')).toBeInTheDocument();
  });
});

describe('DeckTimeline (chart 7)', () => {
  it('renders only horizons that have companies, in fixed order', () => {
    const { container } = render(
      <DeckTimeline companies={sparseCompanies} article={article} alertCreatedAt={createdAt} />,
    );
    const headers = [...container.querySelectorAll('.deck-timeline-step .deck-groupheader')].map(
      (e) => e.textContent ?? '',
    );
    expect(headers[0]).toMatch(/^Immediate/);
    expect(headers[1]).toMatch(/^Short-Term/);
    expect(headers[2]).toMatch(/^Medium-Term/);
    expect(headers).toHaveLength(3); // no Long-Term companies in sparse fixture
  });

  it('gives each horizon its own dot color (not per-direction)', () => {
    const { container } = render(
      <DeckTimeline companies={fullCompanies} article={article} alertCreatedAt={createdAt} />,
    );
    const dots = [...container.querySelectorAll<HTMLElement>('.deck-timeline-dot')].map((e) => e.style.background);
    expect(new Set(dots).size).toBe(dots.length); // all distinct
  });

  it('shows measured move or glyph-only on rows (Doc-1 §2)', () => {
    const { container } = render(
      <DeckTimeline companies={sparseCompanies} article={article} alertCreatedAt={createdAt} />,
    );
    const moves = [...container.querySelectorAll('.deck-crow-move')].map((e) => e.textContent);
    expect(moves).toContain('▼ -1.4%');
    // Unmeasured companies: glyph alone, no number.
    expect(moves.filter((m) => m === '▼')).toHaveLength(2);
  });
});

describe('DeckSectors (chart 8)', () => {
  it('groups by sector with count and mean measured move', () => {
    render(<DeckSectors companies={fullCompanies} article={article} alertCreatedAt={createdAt} />);
    expect(screen.getAllByText(/Banking/).length).toBeGreaterThanOrEqual(1);
    // banking sector: HDFCBANK -1.4, ICICIBANK -1.2, SBIN -1.0, BAJFINANCE
    // -2.1 -> mean -1.4 (formatted with sign).
    expect(screen.getByText(/mean -1\.4%/)).toBeInTheDocument();
  });

  it('omits the mean when nothing in the sector was measured', () => {
    const { container } = render(
      <DeckSectors
        companies={[company({ company_id: 60, ticker: 'TCS', sector: 'it', excess_move_pct: null })]}
        article={article}
        alertCreatedAt={createdAt}
      />,
    );
    const subs = [...container.querySelectorAll('.deck-groupsub')].map((e) => e.textContent ?? '');
    expect(subs.some((s) => s.includes('mean'))).toBe(false);
  });

  it('sub-groups by sub_sector only when more than one bucket exists', () => {
    const { container } = render(
      <DeckSectors companies={fullCompanies} article={article} alertCreatedAt={createdAt} />,
    );
    // banking has nbfc + unclassified -> subgroups render.
    expect(container.querySelectorAll('.deck-subsector').length).toBeGreaterThanOrEqual(2);
  });
});
