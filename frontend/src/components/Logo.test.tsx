import { render, screen } from '@testing-library/react';
import { describe, expect, it, afterEach } from 'vitest';
import Logo from './Logo';
import { ThemeProvider } from '../lib/theme';

afterEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove('light');
});

describe('Logo', () => {
  it('renders with alt text "NewsFlo"', () => {
    render(
      <ThemeProvider>
        <Logo />
      </ThemeProvider>,
    );
    expect(screen.getByAltText('NewsFlo')).toBeInTheDocument();
  });

  it('uses the dark-mode logo asset by default', () => {
    render(
      <ThemeProvider>
        <Logo />
      </ThemeProvider>,
    );
    expect(screen.getByAltText('NewsFlo')).toHaveAttribute('src', expect.stringContaining('logo-dark'));
  });

  it('uses the light-mode logo asset when the stored theme is light', () => {
    localStorage.setItem('newsflo.theme', 'light');
    render(
      <ThemeProvider>
        <Logo />
      </ThemeProvider>,
    );
    expect(screen.getByAltText('NewsFlo')).toHaveAttribute('src', expect.stringContaining('logo-light'));
  });
});
