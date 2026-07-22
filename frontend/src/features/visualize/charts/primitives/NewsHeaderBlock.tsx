import type { AlertArticle } from '../../../../lib/api';

// Shared "what this chart is reacting to" header -- charts 1-9 all open with
// this same inset panel (reference: docs/charts-reference.png). Centered,
// capped width so a long headline still reads as a compact block rather
// than stretching to the card's full width.
export default function NewsHeaderBlock({
  article,
  alertCreatedAt,
}: {
  article: AlertArticle;
  alertCreatedAt: string;
}) {
  return (
    <div className="mx-auto flex w-full max-w-[420px] min-w-[280px] flex-col gap-1 rounded-xl border border-hairline bg-elevated p-3">
      <span className="font-data text-[10px] uppercase tracking-widest text-muted">News</span>
      <p className="line-clamp-2 font-editorial text-[13px] text-ink">{article.title}</p>
      <span className="font-data text-[11px] text-muted">
        {new Date(alertCreatedAt).toLocaleString(undefined, {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        })}
      </span>
    </div>
  );
}
