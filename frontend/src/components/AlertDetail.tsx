import { useEffect, useRef, type ReactNode } from 'react';

export default function AlertDetail({
  open,
  onClose,
  children,
  header,
  hiddenOnMobile = false,
  fullScreenMobile = false,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  // Optional content pinned above the scrollable body, inside the panel --
  // e.g. CalendarModal's day-view back/date/filter bar. Laid out via plain
  // flexbox (fixed-size header + `flex-1 overflow-y-auto` body) rather than
  // `position: sticky` on a child of the scrollable area -- sticky-in-a-
  // padded-scroll-container depends on getting negative-margin/stacking
  // math exactly right and was the source of a recurring "content floats
  // above the header" bug here; a real non-scrolling header can't have that
  // bug by construction.
  header?: ReactNode;
  // The mobile feed carousel expands a card in place instead of using this
  // modal (see AlertCoverCard) -- this instance stays desktop-only so the
  // two behaviors don't both fire off one card tap.
  hiddenOnMobile?: boolean;
  // Mobile only: panel fills the full viewport instead of the usual bottom
  // sheet capped at 85vh. The default bottom sheet leaves a gap above the
  // panel where the page behind shows through the translucent backdrop --
  // fine for a short popup, but for a content-dense view (e.g. the
  // calendar's day list), that gap reads as page content floating above
  // the panel's own header.
  fullScreenMobile?: boolean;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKeyDown);
    panelRef.current?.focus();
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const displayClass = hiddenOnMobile ? 'hidden md:flex' : 'flex';
  const panelSizeClass = fullScreenMobile
    ? 'h-full max-h-full rounded-none md:h-auto md:max-h-[80vh] md:rounded-lg'
    : 'max-h-[85vh] rounded-t-lg md:max-h-[80vh] md:rounded-lg';

  return (
    <div className={`fixed inset-0 z-50 ${displayClass} items-end md:items-center md:justify-center`}>
      <div
        className="absolute inset-0 bg-page/70 motion-safe:transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        className={`relative z-10 flex w-full flex-col overflow-hidden border border-hairline bg-surface outline-none motion-safe:transition-transform md:max-w-lg theme-light:border-transparent theme-light:shadow-neu ${panelSizeClass}`}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute right-4 top-4 z-20 text-muted hover:text-ink"
        >
          ✕
        </button>
        {header && (
          <div className="shrink-0 border-b border-hairline px-6 pb-3 pt-6 theme-light:border-transparent">
            {header}
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto p-6">{children}</div>
      </div>
    </div>
  );
}
