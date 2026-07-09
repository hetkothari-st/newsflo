import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CategorySwatch from './CategorySwatch';

describe('CategorySwatch', () => {
  it('renders a known category label', () => {
    render(<CategorySwatch category="oil_energy" />);
    expect(screen.getByText('Oil & Energy')).toBeInTheDocument();
  });
  it('humanizes an unknown category label', () => {
    render(<CategorySwatch category="some_other" />);
    expect(screen.getByText('some other')).toBeInTheDocument();
  });
});
