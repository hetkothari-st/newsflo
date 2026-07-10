import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import TreeCanvas from './TreeCanvas';
import type { Node, Edge } from 'reactflow';

const nodes: Node[] = [
  { id: 'root', type: 'root', position: { x: 0, y: 0 }, data: { label: 'Event' } },
  {
    id: 'leaf1', type: 'leaf', position: { x: 0, y: 150 },
    data: { label: 'Alpha Co', leaf: { companyId: 7, ticker: 'AAA', name: 'Alpha Co', direction: 'bullish', rationale: 'r' } },
  },
];
const edges: Edge[] = [{ id: 'root->leaf1', source: 'root', target: 'leaf1' }];

describe('TreeCanvas', () => {
  it('renders every node label', () => {
    render(<TreeCanvas nodes={nodes} edges={edges} onLeafClick={() => {}} />);
    expect(screen.getByText('Event')).toBeInTheDocument();
    expect(screen.getByText('Alpha Co')).toBeInTheDocument();
  });

  it('calls onLeafClick with the company id when a leaf node is clicked', () => {
    const onLeafClick = vi.fn();
    render(<TreeCanvas nodes={nodes} edges={edges} onLeafClick={onLeafClick} />);
    fireEvent.click(screen.getByText('Alpha Co'));
    expect(onLeafClick).toHaveBeenCalledWith(7);
  });
});
