import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import App from './App';

describe('App smoke test', () => {
  it('renders the NewsFlo heading', () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: /newsflo/i })).toBeInTheDocument();
  });
});
