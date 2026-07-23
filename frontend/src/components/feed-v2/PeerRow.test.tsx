import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import PeerRow from './PeerRow';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderRow(overrides = {}) {
  const onOpenBusinessPopup = vi.fn();
  const props = {
    ticker: 'BPCL.NS',
    capTier: 'LARGE' as const,
    direction: 'bullish' as const,
    excessMovePct: 3.0,
    intensity: { score: 70, band: 'Moderate' as const, components: [] },
    isExposureOnly: false,
    inMyHoldings: false,
    alertId: 42,
    onOpenBusinessPopup,
    ...overrides,
  };
  render(
    <MemoryRouter>
      <PeerRow {...props} />
    </MemoryRouter>,
  );
  return { onOpenBusinessPopup };
}

describe('PeerRow', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  it('renders ticker, cap tag, excess%, and intensity score', () => {
    renderRow();
    expect(screen.getByText('BPCL.NS')).toBeInTheDocument();
    expect(screen.getByText('LARGE')).toBeInTheDocument();
    expect(screen.getByText(/3\.0%/)).toBeInTheDocument();
    expect(screen.getByText('70')).toBeInTheDocument();
  });

  it('renders Exposure with no number/score when is_exposure_only', () => {
    renderRow({ isExposureOnly: true, excessMovePct: null, intensity: null });
    expect(screen.getByText('Exposure')).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('renders an owned dot only when inMyHoldings is true', () => {
    const { container } = render(
      <MemoryRouter>
        <PeerRow
          ticker="BPCL.NS"
          capTier="LARGE"
          direction="bullish"
          excessMovePct={3.0}
          intensity={{ score: 70, band: 'Moderate', components: [] }}
          isExposureOnly={false}
          inMyHoldings
          alertId={42}
          onOpenBusinessPopup={() => {}}
        />
      </MemoryRouter>,
    );
    expect(container.querySelector('[data-testid="peer-row-owned-dot"]')).toBeInTheDocument();
  });

  it('navigates to the stock deep-dive with alertId on row tap', () => {
    renderRow();
    fireEvent.click(screen.getByRole('button', { name: /BPCL\.NS/ }));
    expect(mockNavigate).toHaveBeenCalledWith('/feed-v2/stock/BPCL.NS?alertId=42');
  });

  it('navigates without an alertId query param when none is given', () => {
    renderRow({ alertId: undefined });
    fireEvent.click(screen.getByRole('button', { name: /BPCL\.NS/ }));
    expect(mockNavigate).toHaveBeenCalledWith('/feed-v2/stock/BPCL.NS');
  });

  it('calls onOpenBusinessPopup and does not navigate when (i) is tapped', () => {
    const { onOpenBusinessPopup } = renderRow();
    fireEvent.click(screen.getByLabelText('View business details'));
    expect(onOpenBusinessPopup).toHaveBeenCalledTimes(1);
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
