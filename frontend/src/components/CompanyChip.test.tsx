import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import CompanyChip from './CompanyChip';
import type { AlertCompany } from '../lib/api';

const company: AlertCompany = {
  company_id: 1,
  ticker: 'RELIANCE.NS',
  name: 'Reliance Industries',
  index_tier: 'NIFTY50',
  direction: 'bullish',
  magnitude_low: 2,
  magnitude_high: 4,
  rationale: 'Refiner margins expand.',
  basis: 'direct_mention',
  confidence: 'llm_estimate',
  in_my_holdings: false,
};

describe('CompanyChip', () => {
  it('shows the company name and a signed magnitude range', () => {
    render(<CompanyChip company={company} />);
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.getByText('+2.0% to +4.0%')).toBeInTheDocument();
  });

  it('is collapsed by default and expands the reasoning panel on click', async () => {
    render(<CompanyChip company={company} />);
    expect(screen.queryByText('Refiner margins expand.')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /reliance/i }));
    expect(screen.getByText('Refiner margins expand.')).toBeInTheDocument();
  });

  it('expands on the Enter key when focused', async () => {
    render(<CompanyChip company={company} />);
    const chip = screen.getByRole('button', { name: /reliance/i });
    chip.focus();
    await userEvent.keyboard('{Enter}');
    expect(screen.getByText('Refiner margins expand.')).toBeInTheDocument();
  });

  it('expands on the Space key when focused', async () => {
    render(<CompanyChip company={company} />);
    const chip = screen.getByRole('button', { name: /reliance/i });
    chip.focus();
    await userEvent.keyboard('{ }');
    expect(screen.getByText('Refiner margins expand.')).toBeInTheDocument();
  });

  it('colors a bearish range with bearish styling', () => {
    render(<CompanyChip company={{ ...company, direction: 'bearish', magnitude_low: -3, magnitude_high: -1 }} />);
    expect(screen.getByText('-3.0% to -1.0%')).toHaveClass('text-bearish');
  });
});
