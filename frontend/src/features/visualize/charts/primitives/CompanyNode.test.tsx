import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import CompanyNode from './CompanyNode';

describe('CompanyNode', () => {
  it('shows name first, ticker second, and the MEASURED move -- never confidence_score', () => {
    render(<CompanyNode name="Lockheed Martin" ticker="LMT" direction="bullish" excessMovePct={3.6} />);
    expect(screen.getByText('Lockheed Martin')).toBeInTheDocument();
    expect(screen.getByText('LMT')).toBeInTheDocument();
    expect(screen.getByText('▲ +3.6%')).toBeInTheDocument();
  });

  it('trims a trailing .0 and keeps the measured sign', () => {
    render(<CompanyNode name="RTX Corporation" ticker="RTX" direction="bearish" excessMovePct={-3} />);
    expect(screen.getByText('▼ -3%')).toBeInTheDocument();
  });

  it('shows the direction glyph ALONE when the company was never measured (chart-spec §2)', () => {
    // The exact prior bug: magnitude/confidence rendered beside the arrow.
    // An unmeasured company must degrade to the glyph, full stop.
    render(<CompanyNode name="Hindalco Industries" ticker="HINDALCO.NS" direction="bearish" />);
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.getByText('▼')).toBeInTheDocument();
  });

  it('shows confidence only as a separate, explicitly labeled line -- never folded into the glyph line', () => {
    render(
      <CompanyNode
        name="Reliance Industries" ticker="RELIANCE" direction="bullish"
        excessMovePct={2.4} confidenceScore={95}
      />,
    );
    expect(screen.getByText('▲ +2.4%')).toBeInTheDocument();
    expect(screen.getByText('Confidence: 95%')).toBeInTheDocument();
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
