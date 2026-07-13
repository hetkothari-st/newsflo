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
    // headline + sentiment, on `page`) and the affected companies (on
    // `surface`, divided by a hairline). flex-1 on the companies block lets
    // its background fill the rest of the scroll column even when the
    // company list is short, so it never trails off into dead blank space.
    // The news block also gets a slight blur once expanded -- a visual cue
    // that it's context, not the focused section -- reinforcing the divide
    // beyond just the hairline.
    return (
      <div className="relative flex h-full w-full shrink-0 snap-start flex-col overflow-y-auto">
        <div className="shrink-0 blur-[2px]">
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
        className="relative aspect-[3/4] w-full shrink-0 cursor-pointer overflow-hidden rounded-lg theme-light:shadow-neu"
      >
        <div className="absolute inset-0">
          <AlertCover imageUrl={alert.article.image_url} category={alert.category} />
        </div>
        <div
          className="absolute inset-0 bg-gradient-to-t from-page/95 via-page/40 to-transparent"
          aria-hidden="true"
        />
        {/* Independent top scrim: the category/time row must stay legible
            over any photo color, not just whatever the bottom gradient's
            faded tail happens to leave behind. */}
        <div
          className="absolute inset-x-0 top-0 h-20 bg-gradient-to-b from-page/90 via-page/50 to-transparent"
          aria-hidden="true"
        />
        <div className="absolute inset-x-0 top-0 flex items-center justify-between p-4">
          <CategorySwatch category={alert.category} active />
          <time className="text-xs uppercase tracking-widest text-ink/80">{formatTime(alert.created_at)}</time>
        </div>
        <div className="absolute inset-x-0 bottom-0 flex flex-col gap-3 p-4">
          <h2 className="font-display text-lg font-bold leading-snug text-ink drop-shadow-sm line-clamp-3">
            {alert.article.title}
          </h2>
          <SentimentPill companies={alert.companies} />
        </div>
      </div>
    );
  }

  // carousel, not expanded: a fixed-height banner -- object-cover fills it
  // exactly, no letterboxed dead space -- with the headline and sentiment
  // flowing normally beneath it, rather than overlaid text on a full-bleed
  // photo. Tapping expands this same card in place (see the `expanded`
  // branch above), not a modal.
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
        <div
          className="absolute inset-x-0 top-0 h-20 bg-gradient-to-b from-page/90 via-page/50 to-transparent"
          aria-hidden="true"
        />
        <div className="absolute inset-x-0 top-0 flex items-center justify-between p-4">
          <CategorySwatch category={alert.category} active />
          <time className="text-xs uppercase tracking-widest text-ink/80">{formatTime(alert.created_at)}</time>
        </div>
      </div>
      <div className="flex flex-1 flex-col justify-center gap-3 p-4">
        <h2 className="font-display text-2xl font-bold leading-snug text-ink line-clamp-4">
          {alert.article.title}
        </h2>
        <SentimentPill companies={alert.companies} />
      </div>
    </div>
  );
}
