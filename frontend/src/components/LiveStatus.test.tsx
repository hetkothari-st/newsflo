import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import LiveStatus from './LiveStatus';
import { LanguageProvider } from '../lib/language';

describe('LiveStatus', () => {
  it('shows Live when connected', () => {
    render(<LanguageProvider><LiveStatus connected /></LanguageProvider>);
    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('shows Reconnecting when the socket is down', () => {
    render(<LanguageProvider><LiveStatus connected={false} /></LanguageProvider>);
    expect(screen.getByText('Reconnecting')).toBeInTheDocument();
  });
});
