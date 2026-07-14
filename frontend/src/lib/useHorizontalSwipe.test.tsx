import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useHorizontalSwipe } from './useHorizontalSwipe';

function Swipeable({ onSwipeLeft, onSwipeRight }: { onSwipeLeft?: () => void; onSwipeRight?: () => void }) {
  const handlers = useHorizontalSwipe({ onSwipeLeft, onSwipeRight });
  return <div data-testid="target" {...handlers} />;
}

function touch(clientX: number, clientY: number) {
  return { touches: [{ clientX, clientY }] } as unknown as React.TouchEvent;
}

describe('useHorizontalSwipe', () => {
  it('fires onSwipeRight when the horizontal drag exceeds the threshold, moving right', () => {
    const onSwipeRight = vi.fn();
    render(<Swipeable onSwipeRight={onSwipeRight} />);
    const target = screen.getByTestId('target');

    target.dispatchEvent(Object.assign(new Event('touchstart', { bubbles: true }), { touches: [{ clientX: 0, clientY: 0 }] }));
    target.dispatchEvent(Object.assign(new Event('touchmove', { bubbles: true }), { touches: [{ clientX: 80, clientY: 5 }] }));
    target.dispatchEvent(new Event('touchend', { bubbles: true }));

    expect(onSwipeRight).toHaveBeenCalledTimes(1);
  });

  it('fires onSwipeLeft when the horizontal drag exceeds the threshold, moving left', () => {
    const onSwipeLeft = vi.fn();
    render(<Swipeable onSwipeLeft={onSwipeLeft} />);
    const target = screen.getByTestId('target');

    target.dispatchEvent(Object.assign(new Event('touchstart', { bubbles: true }), { touches: [{ clientX: 100, clientY: 0 }] }));
    target.dispatchEvent(Object.assign(new Event('touchmove', { bubbles: true }), { touches: [{ clientX: 10, clientY: 5 }] }));
    target.dispatchEvent(new Event('touchend', { bubbles: true }));

    expect(onSwipeLeft).toHaveBeenCalledTimes(1);
  });

  it('does not fire when the drag is vertical-dominant', () => {
    const onSwipeRight = vi.fn();
    const onSwipeLeft = vi.fn();
    render(<Swipeable onSwipeRight={onSwipeRight} onSwipeLeft={onSwipeLeft} />);
    const target = screen.getByTestId('target');

    target.dispatchEvent(Object.assign(new Event('touchstart', { bubbles: true }), { touches: [{ clientX: 0, clientY: 0 }] }));
    target.dispatchEvent(Object.assign(new Event('touchmove', { bubbles: true }), { touches: [{ clientX: 30, clientY: 120 }] }));
    target.dispatchEvent(new Event('touchend', { bubbles: true }));

    expect(onSwipeRight).not.toHaveBeenCalled();
    expect(onSwipeLeft).not.toHaveBeenCalled();
  });

  it('does not fire when the horizontal drag is below the threshold', () => {
    const onSwipeRight = vi.fn();
    render(<Swipeable onSwipeRight={onSwipeRight} />);
    const target = screen.getByTestId('target');

    target.dispatchEvent(Object.assign(new Event('touchstart', { bubbles: true }), { touches: [{ clientX: 0, clientY: 0 }] }));
    target.dispatchEvent(Object.assign(new Event('touchmove', { bubbles: true }), { touches: [{ clientX: 10, clientY: 0 }] }));
    target.dispatchEvent(new Event('touchend', { bubbles: true }));

    expect(onSwipeRight).not.toHaveBeenCalled();
  });
});
