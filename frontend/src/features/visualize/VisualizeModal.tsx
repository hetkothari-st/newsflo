import { useState } from 'react';
import type { Alert } from '../../lib/api';
import ViewPicker, { type ViewType } from './ViewPicker';
import TreeView from './TreeView';
import { buildImpactTree, buildSectorTree } from './transforms';

export default function VisualizeModal({ alert, onClose }: { alert: Alert; onClose: () => void }) {
  const [view, setView] = useState<ViewType>('impact');
  const build = view === 'impact' ? buildImpactTree : buildSectorTree;

  return (
    <div className="fixed inset-0 z-[60] flex flex-col bg-page/95 backdrop-blur-sm" role="dialog" aria-modal="true">
      <div className="flex items-center justify-between border-b border-hairline px-6 py-4">
        <h2 className="truncate font-display text-lg font-bold text-ink">{alert.article.title}</h2>
        <div className="flex items-center gap-4">
          <ViewPicker value={view} onChange={setView} />
          <button type="button" onClick={onClose} aria-label="Close" className="text-muted hover:text-ink">
            ✕
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-hidden">
        {alert.companies.length === 0 ? (
          <p className="p-6 text-sm text-muted">No affected companies for this story.</p>
        ) : (
          <TreeView articleTitle={alert.article.title} companies={alert.companies} build={build} />
        )}
      </div>
    </div>
  );
}
