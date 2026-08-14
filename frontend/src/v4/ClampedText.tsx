/* Line-budgeted text with a truly inline MORE/LESS expander.
   Instead of CSS-clamp + overlay tricks (WebKit clips absolutely-
   positioned children of a -webkit-box, and an overlay can't cover a
   taller text line), the component MEASURES: binary-search the longest
   word prefix that fits the line budget WITH the button's label in
   flow, then render that prefix + an inline button. The button is real
   flow content after the last word -- it can neither overlap nor be
   clipped. Re-measures on width changes; measurement mutates the node
   pre-paint (useLayoutEffect) and restores it, so nothing flashes. */
import { useLayoutEffect, useRef, useState } from 'react';

const SUFFIX_PROBE = '… MORE —';

export default function ClampedText({
  text,
  lines,
  as: Tag = 'p',
  className = '',
}: {
  text: string;
  lines: number;
  as?: 'p' | 'h1';
  className?: string;
}) {
  const ref = useRef<HTMLElement | null>(null);
  // null = full text fits; otherwise the word count that fits with MORE.
  const [cut, setCut] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const lastWidth = useRef(-1);

  useLayoutEffect(() => {
    setOpen(false);
    setCut(null);
    lastWidth.current = -1;
  }, [text]);

  useLayoutEffect(() => {
    const el = ref.current;
    if (el === null || open) return;

    const measure = () => {
      const lineHeight = parseFloat(getComputedStyle(el).lineHeight);
      if (!lineHeight) return;
      const maxHeight = lineHeight * lines + lineHeight * 0.5;
      const previous = el.innerHTML;
      el.textContent = text;
      if (el.scrollHeight <= maxHeight) {
        el.innerHTML = previous;
        setCut(null);
        return;
      }
      const words = text.split(/\s+/).filter(Boolean);
      let low = 1;
      let high = words.length - 1;
      while (low < high) {
        const mid = Math.ceil((low + high) / 2);
        el.textContent = `${words.slice(0, mid).join(' ')}${SUFFIX_PROBE}`;
        if (el.scrollHeight <= maxHeight) low = mid;
        else high = mid - 1;
      }
      el.innerHTML = previous;
      setCut(low);
    };

    measure();
    lastWidth.current = el.clientWidth;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? 0;
      // Only a WIDTH change invalidates the fit -- our own measurement
      // mutations change height and must not re-trigger the observer.
      if (Math.abs(width - lastWidth.current) < 1) return;
      lastWidth.current = width;
      measure();
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [text, lines, open]);

  const swallow = (event: { preventDefault: () => void; stopPropagation: () => void }) => {
    event.preventDefault();
    event.stopPropagation();
  };

  const words = text.split(/\s+/).filter(Boolean);
  const shown = !open && cut !== null ? `${words.slice(0, cut).join(' ')}…` : text;

  return (
    <Tag
      ref={ref as React.RefObject<never>}
      className={`${className} ${open ? 'unclamped' : ''}`.trim()}
    >
      {shown}
      {(open || cut !== null) && (
        <button
          type="button"
          className="morebtn"
          aria-expanded={open}
          onClick={(event) => {
            swallow(event);
            setOpen((prev) => !prev);
          }}
          onTouchStart={(event) => event.stopPropagation()}
          onTouchEnd={(event) => {
            // preventDefault kills the synthetic click -- toggle HERE on
            // touch or the button is dead on touch input.
            swallow(event);
            setOpen((prev) => !prev);
          }}
        >
          {open ? 'Less —' : 'More —'}
        </button>
      )}
    </Tag>
  );
}
