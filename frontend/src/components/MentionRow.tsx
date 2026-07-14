import type { PastMention } from '../lib/api';
import { formatMentionDate } from '../lib/reasoning';
import DirectionArrow from './DirectionArrow';

export default function MentionRow({ mention }: { mention: PastMention }) {
  return (
    <li>
      <a
        href={mention.article_url}
        target="_blank"
        rel="noreferrer"
        className="flex items-baseline gap-2 text-xs text-ink hover:underline"
      >
        <DirectionArrow direction={mention.direction} />
        <span className="flex-1">{mention.article_title}</span>
        <span className="shrink-0 text-muted">{formatMentionDate(mention.created_at)}</span>
      </a>
    </li>
  );
}
