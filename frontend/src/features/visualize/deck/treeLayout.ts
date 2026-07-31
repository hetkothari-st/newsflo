// Pure geometry for the deck's tree-rendering engine (chart-spec Doc-1 §3).
// Computes every rectangle and connector segment for a news-rooted, level-
// banded branching diagram -- no React, no DOM -- so the layout is unit-
// testable exactly as §7 phase 1 requires (nodes fit W, no overlap, single-
// node centers, overflow wraps).
//
// The constants are the approved chart-1 prototype's, tuned once here (§3.2
// "tune once, keep in a config object"). NH is 64 rather than the
// prototype's 52 because the node content is the shared CompanyNode
// primitive (three text lines at the app's own type scale), not the
// prototype's smaller ad-hoc nodebox -- 52 clips its third line. Vertical
// size only affects total H, never the verified horizontal fit.
export const TREE = {
  W: 380, // svg logical width; scales via viewBox to container
  NW: 112, // node box width
  NH: 64, // node box height
  GAPX: 10, // gap between sibling nodes
  ROWGAP: 10, // vertical gap between wrapped rows within one level
  bandH: 26, // height of a level's label row
  levelGap: 34, // vertical space between levels (where edges live)
  // 56, not the prototype's 48: the news box holds a kicker line plus a
  // 2-line clamped headline at the app's type scale; 48 clips line two
  // (verified in a live screenshot).
  newsH: 56,
  newsW: 160,
  BUS_RISE: 8, // the horizontal bus sits this far above a row's node tops
  BOTTOM_PAD: 6,
} as const;

export interface TreeLevelSpec {
  key: string;
  label: string;
  sub: string;
  companyIds: number[];
}

export interface TreeNodePos {
  companyId: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface TreeLevelLayout {
  key: string;
  label: string;
  sub: string;
  labelY: number;
  // Nodes in reading order; `rows` groups the same objects row-by-row for
  // edge drawing (a level with more nodes than fit one row wraps -- §3.2).
  nodes: TreeNodePos[];
  rows: TreeNodePos[][];
  bottomY: number;
}

// One orthogonal connector segment (all edges are vertical/horizontal only,
// §3.3 -- no curves, no arrowheads).
export interface TreeEdgeSegment {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface TreeLayoutResult {
  W: number;
  H: number;
  news: { x: number; y: number; w: number; h: number };
  levels: TreeLevelLayout[];
  edges: TreeEdgeSegment[];
}

// Max nodes per row at full node width. With the §3.2 constants this is 3
// (3*112 + 2*10 = 356 <= 380); a 4th column cannot fit even at the 88px
// shrink floor ((380 - 3*10)/4 = 87.5 < 88), so wrapping -- the doc's
// preferred overflow strategy anyway -- is the only strategy implemented.
function maxPerRow(): number {
  return Math.max(1, Math.floor((TREE.W + TREE.GAPX) / (TREE.NW + TREE.GAPX)));
}

function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

export function layoutTree(levels: TreeLevelSpec[]): TreeLayoutResult {
  const { W, NW, NH, GAPX, ROWGAP, bandH, levelGap, newsH, newsW, BUS_RISE, BOTTOM_PAD } = TREE;
  const centerX = W / 2;

  const news = { x: (W - newsW) / 2, y: 0, w: newsW, h: newsH };
  let y = newsH;

  const levelLayouts: TreeLevelLayout[] = [];
  for (const level of levels) {
    y += levelGap; // edge zone
    const labelY = y;
    y += bandH;

    const rows: TreeNodePos[][] = [];
    for (const [rowIndex, rowIds] of chunk(level.companyIds, maxPerRow()).entries()) {
      if (rowIndex > 0) y += ROWGAP;
      const n = rowIds.length;
      const totalW = n * NW + (n - 1) * GAPX;
      const startX = (W - totalW) / 2;
      rows.push(rowIds.map((companyId, i) => ({ companyId, x: startX + i * (NW + GAPX), y, w: NW, h: NH })));
      y += NH;
    }

    levelLayouts.push({
      key: level.key,
      label: level.label,
      sub: level.sub,
      labelY,
      nodes: rows.flat(),
      rows,
      bottomY: y,
    });
  }

  const H = y + BOTTOM_PAD;

  // Edges (§3.3): trunk at centerX from the news box into the first band,
  // then per level a vertical into a horizontal bus above each row of
  // nodes, a drop from the bus into every node's top-center, and a trunk
  // from the level's bottom into the next band.
  const edges: TreeEdgeSegment[] = [];
  if (levelLayouts.length > 0) {
    edges.push({ x1: centerX, y1: news.y + news.h, x2: centerX, y2: levelLayouts[0].labelY });
  }
  levelLayouts.forEach((level, index) => {
    let prevBottom = level.labelY + bandH - 6; // just under the band label
    for (const row of level.rows) {
      const busY = row[0].y - BUS_RISE;
      edges.push({ x1: centerX, y1: prevBottom, x2: centerX, y2: busY });
      if (row.length > 1) {
        edges.push({
          x1: row[0].x + row[0].w / 2,
          y1: busY,
          x2: row[row.length - 1].x + row[row.length - 1].w / 2,
          y2: busY,
        });
      }
      for (const node of row) {
        edges.push({ x1: node.x + node.w / 2, y1: busY, x2: node.x + node.w / 2, y2: node.y });
      }
      prevBottom = row[0].y + row[0].h;
    }
    if (index < levelLayouts.length - 1) {
      edges.push({ x1: centerX, y1: level.bottomY, x2: centerX, y2: levelLayouts[index + 1].labelY });
    }
  });

  return { W, H, news, levels: levelLayouts, edges };
}
