import { useEffect, type KeyboardEvent } from 'react';
import type { Alert } from '../lib/api';
import AlertCompanies from './AlertCompanies';
import AlertCover from './AlertCover';
import CategorySwatch from './CategorySwatch';
import SentimentPill from './SentimentPill';

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// carousel: one card fills the mobile scroll-snap viewport (see MobileFeedCarousel).
// grid: a fixed-aspect tile inside the desktop grid (see DesktopFeedGrid).
const SIZE_CLASS: Record<'carousel' | 'grid', string> = {
  carousel: 'h-full snap-start',
  grid: 'aspect-[3/4] rounded-lg',
};

// The card's height is fixed (h-full / aspect-[3/4]) but headline length
// isn't -- an unclamped h2 can grow taller than the card and, being
// bottom-anchored, spill upward over the top category/time row. line-clamp
// guarantees a bounded height regardless of headline length or tile width.
// The grid tile is much narrower than a full-screen carousel card, so it
// also gets a smaller headline size and a tighter clamp.
const HEADLINE_CLASS: Record<'carousel' | 'grid', string> = {
  carousel: 'text-2xl line-clamp-4',
  grid: 'text-lg line-clamp-3',
};

export default function AlertCoverCard({
  alert,
  onOpen,
  variant,
  expanded = false,
  onClose,
  isAuthenticated = false,
}: {
  alert: Alert;
  onOpen: () => void;
  variant: 'carousel' | 'grid';
  // Carousel-only: instead of a modal that covers the news up, an opened
  // card expands in place -- the cover shrinks to a banner and the affected
  // companies flow directly beneath it in the same scrollable column.
  expanded?: boolean;
  onClose?: () => void;
  isAuthenticated?: boolean;
}) {
  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onOpen();
    }
  }

  useEffect(() => {
    if (!expanded) return;
    function handleKeyDown(e: globalThis.KeyboardEvent) {
      if (e.key === 'Escape') onClose?.();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [expanded, onClose]);

  if (expanded) {
    return (
      <div className="relative h-full w-full shrink-0 snap-start overflow-y-auto">
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute right-4 top-4 z-20 flex h-8 w-8 items-center justify-center rounded-full bg-page/70 text-ink backdrop-blur-sm hover:text-muted"
        >
          ✕
        </button>
        <div className="relative h-56 w-full shrink-0 overflow-hidden">
          <AlertCover imageUrl={alert.article.image_url} category={alert.category} />
          <div
            className="absolute inset-x-0 top-0 h-20 bg-gradient-to-b from-page/90 via-page/50 to-transparent"
            aria-hidden="true"
          />
          <div className="absolute inset-x-0 top-0 flex items-center justify-between p-4">
            <CategorySwatch category={alert.category} active />
            <time className="text-xs uppercase tracking-widest text-ink/80">{formatTime(alert.created_at)}</time>
          </div>
        </div>
        <div className="flex flex-col gap-3 p-4">
          <h2 className="font-display text-xl font-bold leading-snug text-ink">{alert.article.title}</h2>
          <SentimentPill companies={alert.companies} />
        </div>
        <div className="p-4 pt-0">
          <AlertCompanies alert={alert} isAuthenticated={isAuthenticated} />
        </div>
      </div>
    );
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={onKeyDown}
      className={`relative w-full shrink-0 cursor-pointer overflow-hidden theme-light:shadow-neu ${SIZE_CLASS[variant]}`}
    >
      <div className="absolute inset-0">
        <AlertCover imageUrl={alert.article.image_url} category={alert.category} />
      </div>
      <div
        className="absolute inset-0 bg-gradient-to-t from-page/95 via-page/40 to-transparent"
        aria-hidden="true"
      />
      {/* Independent top scrim: the category/time row must stay legible over
          any photo color, not just whatever the bottom gradient's faded tail
          happens to leave behind. */}
      <div
        className="absolute inset-x-0 top-0 h-20 bg-gradient-to-b from-page/90 via-page/50 to-transparent"
        aria-hidden="true"
      />
      <div className="absolute inset-x-0 top-0 flex items-center justify-between p-4">
        <CategorySwatch category={alert.category} active />
        <time className="text-xs uppercase tracking-widest text-ink/80">{formatTime(alert.created_at)}</time>
      </div>
      <div className="absolute inset-x-0 bottom-0 flex flex-col gap-3 p-4">
        <h2 className={`font-display font-bold leading-snug text-ink drop-shadow-sm ${HEADLINE_CLASS[variant]}`}>
          {alert.article.title}
        </h2>
        <SentimentPill companies={alert.companies} />
      </div>
    </div>
  );
}
