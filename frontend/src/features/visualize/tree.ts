export interface TreeLeafMeta {
  companyId: number;
  ticker: string;
  name: string;
  direction: string;
  rationale: string;
}

export interface TreeNodeData {
  id: string;
  label: string;
  kind: 'root' | 'branch' | 'leaf';
  color?: string;
  leaf?: TreeLeafMeta;
  children: TreeNodeData[];
}
