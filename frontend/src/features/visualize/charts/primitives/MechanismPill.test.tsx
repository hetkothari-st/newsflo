import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import MechanismPill from './MechanismPill';

describe('MechanismPill', () => {
  it('renders the label', () => {
    render(<MechanismPill label="Repo Rate ↓" />);
    expect(screen.getByText('Repo Rate ↓')).toBeInTheDocument();
  });
});
