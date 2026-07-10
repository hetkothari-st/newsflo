import '@testing-library/jest-dom';

// jsdom doesn't implement real scrolling: Element.prototype.scrollTo is
// undefined, and window.scrollTo exists but throws "Not implemented" when
// called. Several components (e.g. Feed's "N new" reveal) call these, so
// stub no-ops globally -- individual tests can still override them with
// their own spy/mock to assert on call args.
Element.prototype.scrollTo = function scrollTo() {};
window.scrollTo = function scrollTo() {};
