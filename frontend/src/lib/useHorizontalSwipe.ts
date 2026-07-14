import { useRef } from 'react';
import type { TouchEvent } from 'react';

// Fires at most one of onSwipeLeft/onSwipeRight per gesture, on touchend,
// once the horizontal drag clears both an absolute threshold AND the
// vertical delta -- so this never fires mid-gesture (no premature nav
// while the user is still deciding) and never fights a vertical
// scroll/scroll-snap gesture on the same element (see AlertCoverCard's
// MobileFeedCarousel, which relies on native vertical snap-scroll).
const THRESHOLD_PX = 60;

export function useHorizontalSwipe(handlers: { onSwipeLeft?: () => void; onSwipeRight?: () => void }) {
  const start = useRef<{ x: number; y: number } | null>(null);
  // Tracks the most recent touchmove position as a fallback for
  // environments where the touchend event carries no touch list (e.g.
  // jsdom's Event-based touch simulation in tests) -- real browsers
  // always populate touchend's changedTouches, which is preferred below.
  const last = useRef<{ x: number; y: number } | null>(null);

  function onTouchStart(e: TouchEvent) {
    const touch = e.touches[0];
    start.current = { x: touch.clientX, y: touch.clientY };
    last.current = null;
  }

  function onTouchMove(e: TouchEvent) {
    const touch = e.touches[0];
    if (touch) last.current = { x: touch.clientX, y: touch.clientY };
  }

  function onTouchEnd(e: TouchEvent) {
    const origin = start.current;
    const fallback = last.current;
    start.current = null;
    last.current = null;
    if (!origin) return;
    const touch = e.changedTouches?.[0];
    const end = touch ? { x: touch.clientX, y: touch.clientY } : fallback;
    if (!end) return;
    const dx = end.x - origin.x;
    const dy = end.y - origin.y;
    if (Math.abs(dx) < THRESHOLD_PX || Math.abs(dx) <= Math.abs(dy)) return;
    if (dx > 0) handlers.onSwipeRight?.();
    else handlers.onSwipeLeft?.();
  }

  return { onTouchStart, onTouchMove, onTouchEnd };
}
