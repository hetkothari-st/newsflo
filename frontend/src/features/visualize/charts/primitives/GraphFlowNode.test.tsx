import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import GraphFlowNode from './GraphFlowNode';

describe('GraphFlowNode', () => {
  it('renders a company node as a CompanyNode tile', () => {
    render(<GraphFlowNode node={{ id: 'company:1', kind: 'company', label: 'LMT', name: 'Lockheed Martin', ticker: 'LMT', direction: 'bullish' }} />);
    expect(screen.getByText('Lockheed Martin')).toBeInTheDocument();
    expect(screen.getByText('LMT')).toBeInTheDocument();
  });

  it('renders a sector node as a SectorNode tile', () => {
    render(<GraphFlowNode node={{ id: 'sector:defense', kind: 'sector', label: 'defense' }} />);
    expect(screen.getByText('Defense')).toBeInTheDocument();
  });

  it('renders a mechanism node as a MechanismPill', () => {
    render(<GraphFlowNode node={{ id: 'mech:a', kind: 'mechanism', label: 'Repo Rate ↓' }} />);
    expect(screen.getByText('Repo Rate ↓')).toBeInTheDocument();
  });

  it('renders a news node as its own small block', () => {
    render(<GraphFlowNode node={{ id: 'news', kind: 'news', label: 'Lockheed wins contract' }} />);
    expect(screen.getByText('News')).toBeInTheDocument();
    expect(screen.getByText('Lockheed wins contract')).toBeInTheDocument();
  });
});
