import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        page: 'rgb(var(--color-page) / <alpha-value>)',
        surface: 'rgb(var(--color-surface) / <alpha-value>)',
        elevated: 'rgb(var(--color-elevated) / <alpha-value>)',
        hairline: 'rgb(var(--color-hairline) / <alpha-value>)',
        ink: 'rgb(var(--color-ink) / <alpha-value>)',
        muted: 'rgb(var(--color-muted) / <alpha-value>)',
        bullish: 'rgb(var(--color-bullish) / <alpha-value>)',
        bearish: 'rgb(var(--color-bearish) / <alpha-value>)',
        accent: 'rgb(var(--color-accent) / <alpha-value>)',
        'accent-secondary': 'rgb(var(--color-accent-secondary) / <alpha-value>)',
        intensityHigh: 'rgb(var(--color-intensity-high) / <alpha-value>)',
        intensityModerate: 'rgb(var(--color-intensity-moderate) / <alpha-value>)',
        intensityLow: 'rgb(var(--color-intensity-low) / <alpha-value>)',
        capLarge: 'rgb(var(--color-cap-large) / <alpha-value>)',
        capMid: 'rgb(var(--color-cap-mid) / <alpha-value>)',
        capSmall: 'rgb(var(--color-cap-small) / <alpha-value>)',
        // Keyed by the fixed category taxonomy (backend/app/analysis/schemas.py
        // CATEGORIES) -- category identity, unchanged across themes.
        swatch: {
          oil_gas: '#F5A623',            // amber
          banking: '#4A90D9',            // blue
          auto: '#2DD4BF',               // teal
          it: '#8B5CF6',                 // violet
          pharma: '#EC4899',             // pink
          fmcg: '#EAB308',               // yellow
          metals: '#78716C',             // stone
          telecom: '#0EA5E9',            // sky
          infra: '#EA580C',              // burnt orange
          macro_policy: '#6366F1',       // indigo
          geopolitics: '#E85D4C',        // red-orange
          corporate_event: '#D97706',    // dark amber
          market_commentary: '#64748B',  // slate
          other: '#8E8E93',              // gray (fallback)
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
        editorial: ["'Newsreader'", 'Georgia', 'serif'],
        data: ["'IBM Plex Mono'", 'monospace'],
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
