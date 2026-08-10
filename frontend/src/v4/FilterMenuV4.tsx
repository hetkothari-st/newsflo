/* Editorial filter dropdown for the broadsheet UI -- replaces native
   <select>, whose open list is OS-rendered (blue highlight, system
   font) and can't match the paper/ink language. Trigger keeps the
   ghost-select look; the open list is a ruled index like the search
   dropdown: hairline rules, hover = hairline ground, the selected entry
   marked by an em-dash and weight instead of a color fill. */
import { useEffect, useRef, useState } from 'react';

export interface FilterOption {
  value: string;
  label: string;
}

export default function FilterMenuV4({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: FilterOption[];
  value: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const selected = options.find((option) => option.value === value);

  useEffect(() => {
    if (!open) return;
    const onDocPointer = (event: PointerEvent) => {
      if (rootRef.current !== null && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('pointerdown', onDocPointer);
    return () => document.removeEventListener('pointerdown', onDocPointer);
  }, [open]);

  useEffect(() => {
    if (!open || activeIndex < 0) return;
    listRef.current
      ?.querySelectorAll('[role="option"]')
      [activeIndex]?.scrollIntoView({ block: 'nearest' });
  }, [open, activeIndex]);

  const toggle = () => {
    setActiveIndex(open ? -1 : options.findIndex((option) => option.value === value));
    setOpen(!open);
  };

  const pick = (option: FilterOption) => {
    onChange(option.value);
    setOpen(false);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (!open) {
      if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        toggle();
      }
      return;
    }
    if (event.key === 'Escape') setOpen(false);
    else if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((index) => Math.min(index + 1, options.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (activeIndex >= 0) pick(options[activeIndex]);
    } else if (event.key === 'Tab') {
      setOpen(false);
    }
  };

  return (
    <div className="fmenu" ref={rootRef} onKeyDown={onKeyDown}>
      <button
        type="button"
        className={`fmenu-btn ${open ? 'open' : ''}`}
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={toggle}
      >
        <span>{selected?.label ?? value}</span>
        <span className="fmenu-caret" aria-hidden="true">
          {open ? '▴' : '▾'}
        </span>
      </button>
      {open && (
        <div className="fmenu-list" role="listbox" aria-label={label} ref={listRef}>
          {options.map((option, index) => {
            const isSelected = option.value === value;
            return (
              <div
                key={option.value}
                role="option"
                aria-selected={isSelected}
                className={`fmenu-item ${isSelected ? 'sel' : ''} ${index === activeIndex ? 'act' : ''}`}
                onPointerEnter={() => setActiveIndex(index)}
                onClick={() => pick(option)}
              >
                <span className="fmenu-mark" aria-hidden="true">
                  {isSelected ? '—' : ''}
                </span>
                {option.label}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
