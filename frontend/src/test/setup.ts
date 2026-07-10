import '@testing-library/jest-dom';

// react-flow (used by the visualize feature) calls ResizeObserver, which
// jsdom does not implement.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}
