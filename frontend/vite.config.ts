/// <reference types="vitest" />
import { defineConfig, defaultExclude } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // Dev-time proxy so the browser talks to the FastAPI backend on :8000
    // through the Vite dev server on :5173 (same-origin fetch + WebSocket).
    // NEWSFLO_API_PORT lets a worktree run its own backend beside the main
    // checkout's :8000 (parallel-session isolation). globalThis-cast keeps
    // tsconfig node-types-free (config runs under Node, app code doesn't).
    proxy: {
      '/api': `http://127.0.0.1:${
        (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env
          .NEWSFLO_API_PORT ?? '8000'
      }`,
      '/ws': {
        target: `ws://127.0.0.1:${
          (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env
            .NEWSFLO_API_PORT ?? '8000'
        }`,
        ws: true,
      },
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
