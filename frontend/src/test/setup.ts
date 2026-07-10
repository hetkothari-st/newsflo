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

// jsdom's synthetic MouseEvent (as constructed by @testing-library/user-event)
// doesn't set `view`, unlike real browsers. d3-drag (used internally by
// react-flow for node/pane dragging) reads `event.view.document` and crashes
// on the resulting null. Default `view` to `window`, matching real browsers.
//
// Getting a real `view` value in this environment takes two patches, not one:
//
// 1. vitest's jsdom environment (`populateGlobal`) copies jsdom window
//    properties onto Node's global object and makes `global.window` a
//    self-reference to that copy rather than the real jsdom `Window`
//    instance, so passing the plain `window` global as `view` fails jsdom's
//    internal "member view is not of type Window" brand check. The real,
//    correctly branded `Window` instance is stashed at `globalThis.jsdom.window`
//    by vitest's jsdom environment setup, so we use that when present.
// 2. Passing `view` to the `MouseEvent` constructor isn't enough by itself:
//    @testing-library/user-event's internal `createEvent()` helper
//    constructs the event and then immediately calls its own `initUIEvent`
//    step, which does `Object.defineProperty(event, 'view', { get: () => ... })`
//    with no `view` in its own init dict — permanently shadowing whatever
//    the constructor set with a non-configurable getter that always returns
//    `null`. So we also patch `Object.defineProperty` itself to catch any
//    `view` accessor that would resolve to a nullish value and fall back it
//    to the real window, regardless of which code path defined it.
const OriginalMouseEvent = globalThis.MouseEvent;
const jsdomWindow =
  (globalThis as unknown as { jsdom?: { window?: Window } }).jsdom?.window ?? window;

class PatchedMouseEvent extends OriginalMouseEvent {
  constructor(type: string, eventInitDict?: MouseEventInit) {
    super(type, { view: jsdomWindow, ...eventInitDict });
  }
}
globalThis.MouseEvent = PatchedMouseEvent as unknown as typeof MouseEvent;

const originalDefineProperty = Object.defineProperty;
Object.defineProperty = function patchedDefineProperty(
  target: object,
  property: PropertyKey,
  descriptor: PropertyDescriptor,
) {
  if (property === 'view' && typeof descriptor.get === 'function') {
    const originalGetter = descriptor.get;
    descriptor = {
      ...descriptor,
      get(this: unknown) {
        const value = originalGetter.call(this);
        return value ?? jsdomWindow;
      },
    };
  }
  return originalDefineProperty(target, property, descriptor);
} as typeof Object.defineProperty;
