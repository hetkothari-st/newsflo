import { render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import HoldingsList from './HoldingsList';
import { LanguageProvider } from '../lib/language';

function render(ui: ReactElement) {
  return rtlRender(<LanguageProvider>{ui}</LanguageProvider>);
}

describe('HoldingsList', () => {
  it('shows an empty state with no holdings', () => {
    render(<HoldingsList holdings={[]} />);
    expect(screen.getByText(/no holdings yet/i)).toBeInTheDocument();
  });

  it('lists holdings with name, ticker and quantity', () => {
    render(<HoldingsList holdings={[{ company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance', quantity: 12 }]} />);
    expect(screen.getByText('Reliance')).toBeInTheDocument();
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
  });
});
