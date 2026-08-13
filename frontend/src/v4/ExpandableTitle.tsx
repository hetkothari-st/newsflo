/* Storycard headline with clamp detection: the card's h1 is clamped to
   4 lines (exact-height snap slots), so long titles cut off with an
   ellipsis. When that actually happens -- and only then -- a subtle
   MORE button appears; clicking it unclamps the title in place (and can
   re-collapse). The button swallows click/touch so it never triggers
   the card's own action (pulse cards are whole-card links; feed cards
   carry tap handlers). */
import { useLayoutEffect, useRef, useState } from 'react';

export default function ExpandableTitle({ title }: { title: string }) {
  const ref = useRef<HTMLHeadingElement>(null);
  const [clamped, setClamped] = useState(false);
  const [open, setOpen] = useState(false);

  useLayoutEffect(() => {
    setOpen(false);
  }, [title]);

  useLayoutEffect(() => {
    const el = ref.current;
    if (el === null || open) return;
    const check = () => {
      // The headline's line-height is < 1, so descenders overflow the
      // line box and scrollHeight runs a few px past clientHeight even
      // when every line is visible. Only a MISSING LINE counts as cut:
      // require at least half a line of hidden text.
      const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 0;
      const hidden = el.scrollHeight - el.clientHeight;
      setClamped(lineHeight > 0 ? hidden > lineHeight * 0.5 : hidden > 4);
    };
    check();
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => observer.disconnect();
  }, [title, open]);

  const swallow = (event: { preventDefault: () => void; stopPropagation: () => void }) => {
    event.preventDefault();
    event.stopPropagation();
  };

  return (
    <>
      <h1 ref={ref} className={open ? 'unclamped' : ''}>
        {title}
      </h1>
      {(clamped || open) && (
        <button
          type="button"
          className="morebtn"
          aria-expanded={open}
          onClick={(event) => {
            swallow(event);
            setOpen((prev) => !prev);
          }}
          onTouchStart={swallow}
          onTouchEnd={swallow}
        >
          {open ? 'Less —' : 'More —'}
        </button>
      )}
    </>
  );
}
