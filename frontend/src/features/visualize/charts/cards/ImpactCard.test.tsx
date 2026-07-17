import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ImpactCard from './ImpactCard';
import type { NetSignal } from '../../transforms';

const SIGNAL: NetSignal = { direction: 'bullish', bullishCount: 1, bearishCount: 0, avgConfidence: 80 };

describe('ImpactCard', () => {
  it('is uncontrolled by default: clicking the header toggles its own collapsed state', () => {
    render(
      <ImpactCard label="Banking" color="#4A90D9" signal={SIGNAL} companyCount={1}>
        <p>child content</p>
      </ImpactCard>,
    );
    expect(screen.getByText('child content')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /banking/i }));
    expect(screen.queryByText('child content')).not.toBeInTheDocument();
  });

  it('is controlled when collapsed is provided: header click calls onToggle instead of flipping local state', () => {
    const onToggle = vi.fn();
    const { rerender } = render(
      <ImpactCard label="Banking" color="#4A90D9" signal={SIGNAL} companyCount={1} collapsed={false} onToggle={onToggle}>
        <p>child content</p>
      </ImpactCard>,
    );
    fireEvent.click(screen.getByRole('button', { name: /banking/i }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    // parent hasn't re-rendered with collapsed=true yet -- content is still visible,
    // proving the click did NOT flip any internal state on its own.
    expect(screen.getByText('child content')).toBeInTheDocument();
    rerender(
      <ImpactCard label="Banking" color="#4A90D9" signal={SIGNAL} companyCount={1} collapsed={true} onToggle={onToggle}>
        <p>child content</p>
      </ImpactCard>,
    );
    expect(screen.queryByText('child content')).not.toBeInTheDocument();
  });

  it('renders a View Details button when onViewDetails is provided, and calls it on click', () => {
    const onViewDetails = vi.fn();
    render(
      <ImpactCard label="Banking" color="#4A90D9" signal={SIGNAL} companyCount={1} onViewDetails={onViewDetails}>
        <p>child content</p>
      </ImpactCard>,
    );
    fireEvent.click(screen.getByRole('button', { name: /view details/i }));
    expect(onViewDetails).toHaveBeenCalledTimes(1);
  });

  it('omits the View Details button when onViewDetails is not provided', () => {
    render(
      <ImpactCard label="Banking" color="#4A90D9" signal={SIGNAL} companyCount={1}>
        <p>child content</p>
      </ImpactCard>,
    );
    expect(screen.queryByRole('button', { name: /view details/i })).not.toBeInTheDocument();
  });
});
