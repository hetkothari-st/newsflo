import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        page: 'rgb(var(--color-page) / <alpha-value>)',
        surface: 'rgb(var(--color-surface) / <alpha-value>)',
        hairline: 'rgb(var(--color-hairline) / <alpha-value>)',
        ink: 'rgb(var(--color-ink) / <alpha-value>)',
        muted: 'rgb(var(--color-muted) / <alpha-value>)',
        bullish: 'rgb(var(--color-bullish) / <alpha-value>)',
        bearish: 'rgb(var(--color-bearish) / <alpha-value>)',
        accent: 'rgb(var(--color-accent) / <alpha-value>)',
        'accent-secondary': 'rgb(var(--color-accent-secondary) / <alpha-value>)',
        swatch: {
          oil_energy: '#F5A623',   // amber -- category identity, unchanged across themes
          banking: '#4A90D9',      // blue
          auto_ev: '#2DD4BF',      // teal
          geopolitics: '#E85D4C',  // red-orange
          other: '#8E8E93',        // gray (fallback)
        },
      },
      fontFamily: {
        display: ['Georgia', "'Times New Roman'", 'serif'],
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          'Inter',
          "'Segoe UI'",
          'sans-serif',
        ],
      },
      borderRadius: {
        lg: '12px',
      },
      maxWidth: {
        feed: '680px',
      },
      letterSpacing: {
        widest: '0.08em',
      },
      boxShadow: {
        // Light-mode-only neumorphic recipes (dual light/dark soft shadow,
        // calibrated against the new light `page` background #E4E8F1).
        // Never referenced unprefixed -- always via `theme-light:`.
        neu: '6px 6px 14px rgb(163 177 198 / 0.45), -6px -6px 14px rgb(255 255 255 / 0.8)',
        'neu-inset': 'inset 4px 4px 10px rgb(163 177 198 / 0.45), inset -4px -4px 10px rgb(255 255 255 / 0.8)',
        'neu-sm': '3px 3px 8px rgb(163 177 198 / 0.4), -3px -3px 8px rgb(255 255 255 / 0.75)',
      },
    },
  },
  plugins: [
    // A `.light` ancestor class (set by ThemeProvider, see frontend/src/lib/theme.tsx)
    // activates `theme-light:*` classes. `:root` itself carries dark values
    // (see index.css), so the ABSENCE of `.light` -- the default, zero-JS
    // state -- already renders today's exact dark theme.
    ({ addVariant }: { addVariant: (name: string, definition: string) => void }) => {
      addVariant('theme-light', '.light &');
    },
  ],
} satisfies Config;
