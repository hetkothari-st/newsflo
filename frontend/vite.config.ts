/// <reference types="vitest" />
import { defineConfig, defaultExclude } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // Dev-time proxy so the browser talks to the FastAPI backend on :8000
    // through the Vite dev server on :5173 (same-origin fetch + WebSocket).
    // NEWSFLO_API_TARGET points the dev proxy at any backend origin
    // (e.g. the Railway preview service, for real data). NEWSFLO_API_PORT
    // keeps the older local-port override (worktree backend beside the
    // main checkout's :8000). globalThis-cast keeps tsconfig
    // node-types-free (config runs under Node, app code doesn't).
    proxy: (() => {
      const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process
        ?.env;
      const target = env?.NEWSFLO_API_TARGET ?? `http://127.0.0.1:${env?.NEWSFLO_API_PORT ?? '8000'}`;
      const wsTarget = target.replace(/^http/, 'ws');
      return {
        '/api': { target, changeOrigin: true },
        '/ws': { target: wsTarget, ws: true, changeOrigin: true },
      };
    })(),
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
