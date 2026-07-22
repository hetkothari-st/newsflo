import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import NewsHeaderBlock from './NewsHeaderBlock';

describe('NewsHeaderBlock', () => {
  it('renders the NEWS label, headline, and formatted timestamp', () => {
    render(
      <NewsHeaderBlock
        article={{ id: 1, title: 'Lockheed to make cheaper Patriot interceptors', url: 'https://example.com', image_url: null }}
        alertCreatedAt="2026-05-15T10:30:00Z"
      />,
    );
    expect(screen.getByText('News')).toBeInTheDocument();
    expect(screen.getByText('Lockheed to make cheaper Patriot interceptors')).toBeInTheDocument();
    expect(screen.getByText(/May 15/)).toBeInTheDocument();
  });
});
