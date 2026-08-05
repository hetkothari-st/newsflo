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

  it('renders a negative ratio -- loss-making figures are real values', () => {
    // Zeros never reach this component anymore: the backend omits BSE's
    // literal "0.00" not-published sentinel at the serve layer. Negatives
    // are the values a truthiness check would wrongly treat as absent.
    render(
      <Fundamentals
        data={{
          classification: { sector: 'Energy', industry: null, group: null, sub_group: null },
          ratios: { npm: -2.05 },
          source: 'BSE',
          as_of: '2026-08-04',
        }}
      />,
    );
    expect(screen.getByText('-2.05')).toBeInTheDocument();
  });

  it('collapses adjacent duplicate classification levels', () => {
    // BSE frequently repeats a level verbatim (L&T: "Construction ›
    // Construction") -- adjacent duplicates read as a rendering bug.
    render(
      <Fundamentals
        data={{
          classification: {
            sector: 'Industrials',
            industry: 'Construction',
            group: 'Construction',
            sub_group: 'Civil Construction',
          },
          source: 'BSE',
          as_of: '2026-08-05',
        }}
      />,
    );
    expect(
      screen.getByText('Industrials › Construction › Civil Construction'),
    ).toBeInTheDocument();
  });

  it('glance variant speaks plain language, demotes abbreviations to tags', () => {
    render(
      <Fundamentals
        variant="glance"
        data={{
          classification: { sector: 'Industrials', industry: null, group: null, sub_group: null },
          ratios: { pe: 76.92, pb: 8.46, roe: 11.0, opm: 16.68, eps: 52.75, ceps: 67.14, npm: 12.37 },
          consolidated: { pe: 28.44, eps: 142.64 },
          source: 'BSE',
          as_of: '2026-08-05',
        }}
      />,
    );
    expect(screen.getByText('Price vs yearly profit')).toBeInTheDocument();
    expect(screen.getByText('76.9×')).toBeInTheDocument();
    expect(screen.getByText('Profit kept from sales')).toBeInTheDocument();
    expect(screen.getByText('16.7%')).toBeInTheDocument();
    expect(screen.getByText("Return on shareholders' money")).toBeInTheDocument();
    expect(screen.getByText('11.0%')).toBeInTheDocument();
    // Abbreviations survive only as small tags for finance-literate readers.
    expect(screen.getByText('P/E')).toBeInTheDocument();
    // No raw codes as primary labels, no P/B, no EPS/CEPS, no consolidated wall.
    expect(screen.queryByText('8.46')).not.toBeInTheDocument();
    expect(screen.queryByText('52.75')).not.toBeInTheDocument();
    expect(screen.queryByText('67.14')).not.toBeInTheDocument();
    expect(screen.queryByText('consolidated')).not.toBeInTheDocument();
    expect(screen.queryByText('28.44')).not.toBeInTheDocument();
  });

  it('glance variant keeps a negative margin -- loss-making is real information', () => {
    render(
      <Fundamentals
        variant="glance"
        data={{
          classification: { sector: 'Energy', industry: null, group: null, sub_group: null },
          ratios: { opm: -3.2 },
          source: 'BSE',
          as_of: '2026-08-05',
        }}
      />,
    );
    expect(screen.getByText('-3.2%')).toBeInTheDocument();
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

  it('renders consolidated ratios beneath standalone ones, labelled "consolidated"', () => {
    render(
      <Fundamentals
        data={{
          classification: { sector: 'Energy', industry: null, group: null, sub_group: null },
          ratios: { pe: 44.95 },
          consolidated: { pe: 40.12, opm: 18.5 },
          source: 'BSE',
          as_of: '2026-08-04',
        }}
      />,
    );
    expect(screen.getByText('consolidated')).toBeInTheDocument();
    expect(screen.getByText('44.95')).toBeInTheDocument();
    expect(screen.getByText('40.12')).toBeInTheDocument();
    expect(screen.getByText('18.50')).toBeInTheDocument();
  });

  it('renders consolidated ratios even when no standalone ratio is present', () => {
    render(
      <Fundamentals
        data={{
          classification: { sector: 'Energy', industry: null, group: null, sub_group: null },
          consolidated: { npm: 3.41 },
          source: 'BSE',
          as_of: '2026-08-04',
        }}
      />,
    );
    expect(screen.getByText('consolidated')).toBeInTheDocument();
    expect(screen.getByText('3.41')).toBeInTheDocument();
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
