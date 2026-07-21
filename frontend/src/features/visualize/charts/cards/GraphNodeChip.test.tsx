import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import GraphNodeChip from './GraphNodeChip';
import type { GraphNode } from '../../../../lib/api';

function node(overrides: Partial<GraphNode>): GraphNode {
  return { id: 'n1', kind: 'sector', label: 'banking', ...overrides };
}

describe('GraphNodeChip', () => {
  it('renders a company node with ticker, name, and direction glyph/confidence', () => {
    render(<GraphNodeChip node={node({ kind: 'company', company_id: 1, ticker: 'HDFCBANK.NS', name: 'HDFC Bank', direction: 'bullish', confidence_score: 80 })} />);
    expect(screen.getByText('HDFCBANK.NS')).toBeInTheDocument();
    expect(screen.getByText('HDFC Bank')).toBeInTheDocument();
    expect(screen.getByText('▲ 80%')).toBeInTheDocument();
  });

  it('renders a sector node with its label, not a ticker/confidence', () => {
    render(<GraphNodeChip node={node({ kind: 'sector', label: 'banking' })} />);
    expect(screen.getByText('Banking')).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('renders a mechanism node with its raw label', () => {
    render(<GraphNodeChip node={node({ kind: 'mechanism', label: 'Repo Rate ↓' })} />);
    expect(screen.getByText('Repo Rate ↓')).toBeInTheDocument();
  });

  it('renders a news node with its label', () => {
    render(<GraphNodeChip node={node({ kind: 'news', label: 'RBI cuts repo rate by 25bps' })} />);
    expect(screen.getByText('RBI cuts repo rate by 25bps')).toBeInTheDocument();
  });

  it('shows the portfolio ring for a held company node', () => {
    render(<GraphNodeChip node={node({ kind: 'company', company_id: 1, ticker: 'AAA', name: 'Alpha', direction: 'bullish', confidence_score: 50, in_my_holdings: true })} />);
    expect(screen.getByText('AAA').closest('div')).toHaveClass('ring-2', 'ring-accent-secondary');
  });

  it('is a clickable button when onClick is provided', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    const onClick = vi.fn();
    render(<GraphNodeChip node={node({ kind: 'company', company_id: 1, ticker: 'AAA', name: 'Alpha', direction: 'bullish', confidence_score: 50 })} onClick={onClick} />);
    await userEvent.click(screen.getByText('AAA'));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('is a plain non-interactive block when onClick is omitted', () => {
    render(<GraphNodeChip node={node({ kind: 'sector', label: 'banking' })} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
