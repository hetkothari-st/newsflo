import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { TreeRoot, TreeBranch, TreeLeaf } from './Tree';

describe('TreeBranch', () => {
  it('renders its label and children expanded by default', () => {
    render(
      <TreeRoot>
        <TreeBranch label="Oil & Gas">
          <TreeLeaf ticker="RIL" direction="bullish" onClick={vi.fn()} />
        </TreeBranch>
      </TreeRoot>,
    );
    expect(screen.getByText('Oil & Gas')).toBeInTheDocument();
    expect(screen.getByText('RIL')).toBeInTheDocument();
  });

  it('collapses and re-expands children on click, without unmounting them', async () => {
    render(
      <TreeRoot>
        <TreeBranch label="Oil & Gas">
          <TreeLeaf ticker="RIL" direction="bullish" onClick={vi.fn()} />
        </TreeBranch>
      </TreeRoot>,
    );
    expect(screen.getByText('RIL')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Oil & Gas'));
    expect(screen.queryByText('RIL')).not.toBeInTheDocument();
    await userEvent.click(screen.getByText('Oil & Gas'));
    expect(screen.getByText('RIL')).toBeInTheDocument();
  });

  it('shows a colored dot when a color is given, none when omitted', () => {
    const { container, rerender } = render(
      <TreeRoot>
        <TreeBranch label="Oil & Gas" color="#E85D4C">
          <TreeLeaf ticker="RIL" direction="bullish" onClick={vi.fn()} />
        </TreeBranch>
      </TreeRoot>,
    );
    expect(container.querySelector('[style*="E85D4C"]')).not.toBeNull();

    rerender(
      <TreeRoot>
        <TreeBranch label="Oil & Gas">
          <TreeLeaf ticker="RIL" direction="bullish" onClick={vi.fn()} />
        </TreeBranch>
      </TreeRoot>,
    );
    expect(container.querySelector('[style*="background-color"]')).toBeNull();
  });

  it('tints the connector line (child ul border-color) with the branch color', () => {
    const { container } = render(
      <TreeRoot>
        <TreeBranch label="Oil & Gas" color="#E85D4C">
          <TreeLeaf ticker="RIL" direction="bullish" onClick={vi.fn()} />
        </TreeBranch>
      </TreeRoot>,
    );
    const list = container.querySelector('ul ul');
    expect(list).not.toBeNull();
    expect(list?.getAttribute('style')).toContain('E85D4C');
    expect(list?.getAttribute('style')).toMatch(/border-?color/i);
  });
});

describe('TreeLeaf', () => {
  it('renders ticker, direction glyph, and an optional badge', () => {
    render(
      <TreeRoot>
        <TreeLeaf ticker="RIL" direction="bearish" badge="72%" onClick={vi.fn()} />
      </TreeRoot>,
    );
    expect(screen.getByText('RIL')).toBeInTheDocument();
    expect(screen.getByText('72%')).toBeInTheDocument();
    expect(screen.getByText('▼')).toBeInTheDocument();
  });

  it('calls onClick when tapped', async () => {
    const onClick = vi.fn();
    render(
      <TreeRoot>
        <TreeLeaf ticker="RIL" direction="bullish" onClick={onClick} />
      </TreeRoot>,
    );
    await userEvent.click(screen.getByText('RIL'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('colors the badge when badgeColor is given', () => {
    render(
      <TreeRoot>
        <TreeLeaf ticker="RIL" direction="bullish" badge="91%" badgeColor="#5C8ACE" onClick={vi.fn()} />
      </TreeRoot>,
    );
    expect(screen.getByText('91%')).toHaveStyle({ color: '#5C8ACE' });
  });
});
