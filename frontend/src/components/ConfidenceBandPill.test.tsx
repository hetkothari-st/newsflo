import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ConfidenceBandPill from './ConfidenceBandPill';
import { LanguageProvider } from '../lib/language';
import { confidenceBandColor } from '../features/visualize/colors';

function renderPill(band: string | null | undefined) {
  return render(
    <LanguageProvider>
      <ConfidenceBandPill band={band} />
    </LanguageProvider>,
  );
}

describe('ConfidenceBandPill', () => {
  it('renders the HIGH label colored via confidenceBandColor', () => {
    renderPill('HIGH');
    const el = screen.getByText('High');
    expect(el).toHaveStyle({ color: confidenceBandColor('HIGH') });
  });

  it('renders the VERY_HIGH label as "Very High"', () => {
    renderPill('VERY_HIGH');
    expect(screen.getByText('Very High')).toBeInTheDocument();
  });

  it('renders nothing for a null band (legacy alert)', () => {
    const { container } = renderPill(null);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for an undefined band', () => {
    const { container } = renderPill(undefined);
    expect(container).toBeEmptyDOMElement();
  });
});
