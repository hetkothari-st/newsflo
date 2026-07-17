import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ChartCardShell from './ChartCardShell';

describe('ChartCardShell', () => {
  it('renders the numbered badge, title, description, and children', () => {
    render(
      <ChartCardShell number={5} title="Confidence Tree" description="Tree showing companies with confidence scores">
        <p>chart body</p>
      </ChartCardShell>,
    );
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('Confidence Tree')).toBeInTheDocument();
    expect(screen.getByText('Tree showing companies with confidence scores')).toBeInTheDocument();
    expect(screen.getByText('chart body')).toBeInTheDocument();
  });

  it('renders legend items when provided', () => {
    render(
      <ChartCardShell number={5} title="Confidence Tree" description="desc" legend={[{ label: 'High Confidence', color: '#25508F' }]}>
        <p>body</p>
      </ChartCardShell>,
    );
    expect(screen.getByText('High Confidence')).toBeInTheDocument();
  });

  it('omits the legend row entirely when legend is not provided', () => {
    const { container } = render(
      <ChartCardShell number={5} title="Confidence Tree" description="desc">
        <p>body</p>
      </ChartCardShell>,
    );
    expect(container.querySelector('[data-testid="chart-legend"]')).toBeNull();
  });
});
