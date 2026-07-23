/// <reference types="vitest" />
import { defineConfig, defaultExclude } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // Dev-time proxy so the browser talks to the FastAPI backend on :8000
    // through the Vite dev server on :5173 (same-origin fetch + WebSocket).
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    // Playwright's e2e specs (frontend/e2e/**) declare their own `test()`
    // via @playwright/test, not vitest -- collecting them here throws
    // ("Playwright Test did not expect test() to be called here").
    exclude: [...defaultExclude, '**/e2e/**'],
  },
});
