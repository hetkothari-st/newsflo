import { useMemo, useState } from 'react';
import type { AlertCompany } from '../../lib/api';
import type { TreeNodeData } from './tree';
import { layoutTree } from './treeLayout';
import TreeCanvas from './TreeCanvas';
import ReasoningPanel from '../../components/ReasoningPanel';

export default function TreeView({
  articleTitle,
  companies,
  build,
}: {
  articleTitle: string;
  companies: AlertCompany[];
  build: (articleTitle: string, companies: AlertCompany[]) => TreeNodeData;
}) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const { nodes, edges } = useMemo(() => layoutTree(build(articleTitle, companies)), [articleTitle, companies, build]);
  const selected = companies.find((c) => c.company_id === selectedId) ?? null;

  return (
    <div className="flex h-full">
      <div className="min-w-0 flex-1">
        <TreeCanvas nodes={nodes} edges={edges} onLeafClick={setSelectedId} />
      </div>
      {selected && (
        <div className="w-72 shrink-0 overflow-y-auto border-l border-hairline p-4">
          <ReasoningPanel company={selected} />
        </div>
      )}
    </div>
  );
}
