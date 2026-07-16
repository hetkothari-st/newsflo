import { useEffect, useRef, type ReactNode } from 'react';

export default function AlertDetail({
  open,
  onClose,
  children,
  hiddenOnMobile = false,
  fullScreenMobile = false,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  // The mobile feed carousel expands a card in place instead of using this
  // modal (see AlertCoverCard) -- this instance stays desktop-only so the
  // two behaviors don't both fire off one card tap.
  hiddenOnMobile?: boolean;
  // Mobile only: panel fills the full viewport instead of the usual bottom
  // sheet capped at 85vh. The default bottom sheet leaves a gap above the
  // panel where the page behind shows through the translucent backdrop --
  // fine for a short popup, but for a content-dense view with its own
  // sticky in-panel header (e.g. CalendarModal's day list), that gap reads
  // as page content floating above the sticky header instead of backdrop.
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
        className={`relative z-10 w-full overflow-y-auto border border-hairline bg-surface p-6 outline-none motion-safe:transition-transform md:max-w-lg theme-light:border-transparent theme-light:shadow-neu ${panelSizeClass}`}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          // z-20, above z-10 sticky content (e.g. CalendarModal's day-view
          // header bar) that a scrolled child might otherwise paint over.
          className="absolute right-4 top-4 z-20 text-muted hover:text-ink"
        >
          ✕
        </button>
        {children}
      </div>
    </div>
  );
}
