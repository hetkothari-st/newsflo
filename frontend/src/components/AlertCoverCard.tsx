import type { KeyboardEvent } from 'react';
import type { Alert } from '../lib/api';
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

export default function AlertCoverCard({
  alert,
  onOpen,
  variant,
}: {
  alert: Alert;
  onOpen: () => void;
  variant: 'carousel' | 'grid';
}) {
  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onOpen();
    }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={onKeyDown}
      className={`relative w-full shrink-0 cursor-pointer overflow-hidden ${SIZE_CLASS[variant]}`}
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
        <h2 className="font-display text-2xl font-bold leading-snug text-ink drop-shadow-sm">
          {alert.article.title}
        </h2>
        <SentimentPill companies={alert.companies} />
      </div>
    </div>
  );
}
