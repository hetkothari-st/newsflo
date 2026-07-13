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

// The grid tile's height is fixed (aspect-[3/4]) but headline length isn't
// -- an unclamped h2 can grow taller than the tile and, being
// bottom-anchored, spill upward over the top category/time row. line-clamp
// guarantees a bounded height regardless of headline length or tile width.
const GRID_SIZE_CLASS = 'aspect-[3/4] rounded-lg';
const GRID_HEADLINE_CLASS = 'text-lg line-clamp-3';

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
    // Bifurcated into two clearly distinct blocks: the news (cover banner +
    // headline + sentiment) and the affected companies (on `surface`,
    // divided by a hairline). A translucent frosted veil over the news
    // block -- image and headline both -- reads as "receded, context" next
    // to the crisp, focused companies section below. flex-1 on the
    // companies block lets its background fill the rest of the scroll
    // column even when the company list is short, so it never trails off
    // into dead blank space.
    return (
      <div className="relative flex h-full w-full shrink-0 snap-start flex-col overflow-y-auto">
        <div className="relative shrink-0">
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
          <div className="absolute inset-0 bg-page/70 backdrop-blur-[2px]" aria-hidden="true" />
        </div>
        <div className="flex-1 border-t border-hairline bg-surface p-4 theme-light:border-transparent theme-light:shadow-neu-inset">
          <AlertCompanies
            alert={alert}
            isAuthenticated={isAuthenticated}
            headerRight={
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="flex h-6 w-6 items-center justify-center text-muted hover:text-ink"
              >
                ✕
              </button>
            }
          />
        </div>
      </div>
    );
  }

  if (variant === 'grid') {
    return (
      <div
        role="button"
        tabIndex={0}
        onClick={onOpen}
        onKeyDown={onKeyDown}
        className={`relative w-full shrink-0 cursor-pointer overflow-hidden theme-light:shadow-neu ${GRID_SIZE_CLASS}`}
      >
        <div className="absolute inset-0">
          <AlertCover imageUrl={alert.article.image_url} category={alert.category} />
        </div>
        <div
          className="absolute inset-0 bg-gradient-to-t from-page/95 via-page/40 to-transparent"
          aria-hidden="true"
        />
        <div className="absolute inset-x-0 top-0 flex items-center justify-between p-4">
          <CategorySwatch category={alert.category} active />
          <time className="text-xs uppercase tracking-widest text-ink/80">{formatTime(alert.created_at)}</time>
        </div>
        <div className="absolute inset-x-0 bottom-0 flex flex-col gap-3 p-4">
          <h2 className={`font-display font-bold leading-snug text-ink drop-shadow-sm ${GRID_HEADLINE_CLASS}`}>
            {alert.article.title}
          </h2>
          <SentimentPill companies={alert.companies} />
        </div>
      </div>
    );
  }

  // carousel, not expanded: a fixed-height banner (object-cover fills it
  // exactly -- no letterboxed dead space, no blur) with the category/time
  // row in small pill chips rather than a full-width gradient wash, and the
  // headline/sentiment flowing normally beneath the banner instead of
  // overlaid on it -- nothing ever sits translucent in front of the photo
  // or the text. Tapping expands this same card in place (see the
  // `expanded` branch above), not a modal.
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={onKeyDown}
      className="relative flex h-full w-full shrink-0 cursor-pointer flex-col overflow-hidden snap-start theme-light:shadow-neu"
    >
      <div className="relative h-72 w-full shrink-0 overflow-hidden">
        <AlertCover imageUrl={alert.article.image_url} category={alert.category} />
        <div className="absolute inset-x-0 top-0 flex items-center justify-between p-3">
          <span className="inline-flex items-center rounded-full bg-page/85 px-2.5 py-1 backdrop-blur-sm">
            <CategorySwatch category={alert.category} active />
          </span>
          <time className="rounded-full bg-page/85 px-2.5 py-1 text-xs uppercase tracking-widest text-ink backdrop-blur-sm">
            {formatTime(alert.created_at)}
          </time>
        </div>
      </div>
      <div className="flex flex-col gap-3 p-4">
        <h2 className="font-display text-2xl font-bold leading-snug text-ink line-clamp-4">
          {alert.article.title}
        </h2>
        <SentimentPill companies={alert.companies} />
      </div>
    </div>
  );
}
