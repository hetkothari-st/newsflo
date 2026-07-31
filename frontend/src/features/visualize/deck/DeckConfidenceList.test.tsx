import { render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { LanguageProvider } from '../../../lib/language';
import DeckConfidenceList from './DeckConfidenceList';
import { article, createdAt, fullCompanies, sparseCompanies } from './fixtures';

function render(ui: ReactElement) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>{ui}</LanguageProvider>
    </MemoryRouter>,
  );
}

describe('DeckConfidenceList (chart 5)', () => {
  it('groups by confidence band, sorted desc within each', () => {
    const { container } = render(
      <DeckConfidenceList companies={fullCompanies} article={article} alertCreatedAt={createdAt} />,
    );
    // Band name appears as the group header AND each row's own band label.
    expect(screen.getAllByText('High').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Medium').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Low').length).toBeGreaterThanOrEqual(2);
    const scores = [...container.querySelectorAll('.deck-confscore')].map((e) => Number(e.textContent));
    expect(scores).toEqual([88, 84, 78, 66, 61, 55, 48, 44, 38]);
  });

  it('renders a fill bar sized by confidence and a 70% threshold marker', () => {
    const { container } = render(
      <DeckConfidenceList companies={sparseCompanies} article={article} alertCreatedAt={createdAt} />,
    );
    const fills = [...container.querySelectorAll<HTMLElement>('.deck-conffill')].map((e) => e.style.width);
    expect(fills).toEqual(['88%', '64%', '42%']);
    const markers = [...container.querySelectorAll<HTMLElement>('.deck-confthreshold')];
    expect(markers).toHaveLength(3);
    expect(markers[0].style.left).toBe('70%');
  });

  it('never renders a direction arrow beside the confidence number (Doc-1 §2)', () => {
    const { container } = render(
      <DeckConfidenceList companies={fullCompanies} article={article} alertCreatedAt={createdAt} />,
    );
    expect(container.textContent).not.toMatch(/[▲▼]/);
  });
});
