import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import LiveStatus from './LiveStatus';

describe('LiveStatus', () => {
  it('shows Live when connected', () => {
    render(<LiveStatus connected />);
    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('shows Reconnecting when the socket is down', () => {
    render(<LiveStatus connected={false} />);
    expect(screen.getByText('Reconnecting')).toBeInTheDocument();
  });
});
