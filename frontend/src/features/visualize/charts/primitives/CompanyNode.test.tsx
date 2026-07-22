import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import CompanyNode from './CompanyNode';

describe('CompanyNode', () => {
  it('shows name first, ticker second, and the magnitude range -- never confidence_score', () => {
    render(<CompanyNode name="Lockheed Martin" ticker="LMT" direction="bullish" magnitudeLow={2} magnitudeHigh={4} />);
    expect(screen.getByText('Lockheed Martin')).toBeInTheDocument();
    expect(screen.getByText('LMT')).toBeInTheDocument();
    expect(screen.getByText('▲ +2%–+4%')).toBeInTheDocument();
  });

  it('collapses to a single value when magnitude_low equals magnitude_high', () => {
    render(<CompanyNode name="RTX Corporation" ticker="RTX" direction="bearish" magnitudeLow={-3} magnitudeHigh={-3} />);
    expect(screen.getByText('▼ -3%')).toBeInTheDocument();
  });

  it('shows the direction glyph alone, never a confidence value, when magnitude is absent', () => {
    render(<CompanyNode name="Hindalco Industries" ticker="HINDALCO.NS" direction="bearish" />);
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.getByText('▼')).toBeInTheDocument();
  });

  it('calls onClick and reflects selected state when interactive', async () => {
    const onClick = vi.fn();
    render(<CompanyNode name="RIL" ticker="RELIANCE.NS" direction="bullish" onClick={onClick} selected />);
    const button = screen.getByRole('button');
    expect(button).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('renders as a non-interactive div when onClick is omitted', () => {
    render(<CompanyNode name="RIL" ticker="RELIANCE.NS" direction="bullish" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
