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

// jsdom doesn't implement real scrolling: Element.prototype.scrollTo is
// undefined, and window.scrollTo exists but throws "Not implemented" when
// called. Several components (e.g. Feed's "N new" reveal) call these, so
// stub no-ops globally -- individual tests can still override them with
// their own spy/mock to assert on call args.
Element.prototype.scrollTo = function scrollTo() {};
window.scrollTo = function scrollTo() {};
