import type { JSX, ReactNode } from 'react';
import type { AlertCompany } from '../../../lib/api';
import { TREE, layoutTree, type TreeLevelSpec } from './treeLayout';
import './deck.css';

// The deck's tree-rendering engine (chart-spec Doc-1 §3) -- one reusable
// renderer; Impact Tree (#1) and Multi-Level Tree (#4) are configurations
// of it. Draws a REAL branching diagram: news root, ordered level bands,
// nodes centered per level, orthogonal trunk -> bus -> drop connectors. A
// tree without drawn edges is a list and gets rejected (§0.1) -- the edges
// here come from layoutTree's segment list, never CSS borders.
//
// Text positioning rules (§3.4, the stray-line/misaligned-label fixes):
// node text renders as HTML inside <foreignObject> (crisp, browser-laid-
// out), and the band sub-label hangs off the main label via <tspan dx> --
// no pixel width is ever estimated from character count anywhere here.

export interface TreeConfig {
  newsLabel: string; // e.g. "News · 22 Jul"
  newsHeadline: string;
  levels: TreeLevelSpec[]; // ordered top -> bottom
  nodeContent: (c: AlertCompany) => ReactNode; // what renders inside a node box
}

export function renderTree(cfg: TreeConfig, companies: AlertCompany[]): JSX.Element {
  const byId = new Map(companies.map((c) => [c.company_id, c]));
  // Sparse-data honesty (§6): a level whose companies can't be resolved to
  // real rows is dropped rather than rendered as empty boxes -- nothing on
  // this chart may exist without a backing AlertCompany row.
  const levels = cfg.levels
    .map((level) => ({ ...level, companyIds: level.companyIds.filter((id) => byId.has(id)) }))
    .filter((level) => level.companyIds.length > 0);
  const layout = layoutTree(levels);

  return (
    <svg
      className="deck-tree"
      viewBox={`0 0 ${layout.W} ${layout.H}`}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label={cfg.newsHeadline}
    >
      {layout.edges.map((edge, i) => (
        <path
          key={`edge-${i}`}
          className="deck-edge"
          d={`M ${edge.x1} ${edge.y1} L ${edge.x2} ${edge.y2}`}
        />
      ))}
      {layout.levels.map((level) => (
        // Label + sub in ONE <text>, sub spaced by the browser via tspan dx
        // (§3.4). No trailing divider rule after the label.
        <text key={`label-${level.key}`} className="deck-bandlabel" x={level.rows[0][0].x} y={level.labelY + 13}>
          {level.label}
          <tspan className="deck-bandsub" dx="12">
            {level.sub}
          </tspan>
        </text>
      ))}
      <foreignObject x={layout.news.x} y={layout.news.y} width={layout.news.w} height={layout.news.h}>
        <div className="deck-newsbox">
          <span className="deck-newskicker">{cfg.newsLabel}</span>
          <span className="deck-newsheadline">{cfg.newsHeadline}</span>
        </div>
      </foreignObject>
      {layout.levels.map((level) =>
        level.nodes.map((node) => {
          const company = byId.get(node.companyId);
          if (!company) return null;
          return (
            <foreignObject key={`node-${level.key}-${node.companyId}`} x={node.x} y={node.y} width={node.w} height={node.h}>
              <div className="deck-nodefit">{cfg.nodeContent(company)}</div>
            </foreignObject>
          );
        }),
      )}
    </svg>
  );
}

export { TREE };
