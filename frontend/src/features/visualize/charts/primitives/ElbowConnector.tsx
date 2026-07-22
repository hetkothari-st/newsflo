// Plain 1px vertical drop, no arrowhead, muted at ~40% opacity -- the
// stacked-flow connector used between the news block and the first level
// band, and between successive level bands. Orthogonal (horizontal-run)
// elbow edges for node-link charts (Ripple, Supply Chain) are drawn as SVG
// paths in those charts directly, since they need real measured coordinates
// between two arbitrary points rather than a fixed vertical drop.
export default function ElbowConnector({ height = 16 }: { height?: number }) {
  return (
    <div aria-hidden="true" className="flex justify-center">
      <span style={{ height }} className="w-px bg-muted/40" />
    </div>
  );
}
