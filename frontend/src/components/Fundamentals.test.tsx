import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import Fundamentals from './Fundamentals';

describe('Fundamentals', () => {
  it('renders the classification path, ratios, source, and as-of date', () => {
    render(
      <Fundamentals
        data={{
          classification: {
            sector: 'Energy',
            industry: 'Oil, Gas & Consumable Fuels',
            group: 'Petroleum Products',
            sub_group: 'Refineries & Marketing',
          },
          ratios: { pe: 44.95, opm: 14.24 },
          source: 'BSE',
          as_of: '2026-08-04',
        }}
      />,
    );
    expect(screen.getByText('Energy › Oil, Gas & Consumable Fuels › Petroleum Products › Refineries & Marketing')).toBeInTheDocument();
    expect(screen.getByText('44.95')).toBeInTheDocument();
    expect(screen.getByText('14.24')).toBeInTheDocument();
    expect(screen.getByText('BSE · as of 2026-08-04')).toBeInTheDocument();
  });

  it('renders a real zero ratio as 0.00 rather than omitting it', () => {
    render(
      <Fundamentals
        data={{
          classification: { sector: 'Energy', industry: null, group: null, sub_group: null },
          ratios: { npm: 0.0 },
          source: 'BSE',
          as_of: '2026-08-04',
        }}
      />,
    );
    expect(screen.getByText('0.00')).toBeInTheDocument();
  });

  it('renders nothing when data is null', () => {
    const { container } = render(<Fundamentals data={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when data is undefined', () => {
    const { container } = render(<Fundamentals data={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('omits the ratios list entirely when no ratio is present', () => {
    const { container } = render(
      <Fundamentals
        data={{
          classification: { sector: 'Energy', industry: null, group: null, sub_group: null },
          source: 'BSE',
          as_of: '2026-08-04',
        }}
      />,
    );
    expect(container.querySelector('dl')).toBeNull();
  });

  it('falls back to "source unknown" when source is null', () => {
    render(
      <Fundamentals
        data={{
          classification: { sector: 'Energy', industry: null, group: null, sub_group: null },
          source: null,
          as_of: '2026-08-04',
        }}
      />,
    );
    expect(screen.getByText('source unknown · as of 2026-08-04')).toBeInTheDocument();
  });
});
