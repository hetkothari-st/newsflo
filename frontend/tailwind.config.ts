import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        page: '#0A0A0A',       // near-true-black page background
        surface: '#161616',    // card surface, one step up from page bg
        hairline: '#262626',   // card border, hairline
        ink: '#F2F2F2',        // primary text
        muted: '#8E8E93',      // secondary / metadata text
        bullish: '#34C759',
        bearish: '#FF453A',
        swatch: {
          oil_energy: '#F5A623',   // amber
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
        lg: '12px', // CRED-style moderate radius (~12px), per spec token
      },
      maxWidth: {
        feed: '680px',
      },
      letterSpacing: {
        widest: '0.08em', // tracked-uppercase metadata/tabs/buttons
      },
    },
  },
  plugins: [],
} satisfies Config;
