import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ElbowConnector from './ElbowConnector';

describe('ElbowConnector', () => {
  it('renders as a decorative, screen-reader-hidden element', () => {
    const { container } = render(<ElbowConnector />);
    expect(container.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
  });
});
