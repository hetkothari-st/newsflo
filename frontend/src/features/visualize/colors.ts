// Fixed-order categorical palette, one color per known Company.sector value
// (confirmed against real data: oil_gas, banking, auto, it, pharma, fmcg,
// metals, telecom, infra, other -- see backend/app/analysis/schemas.py's
// SECTORS enum, which Company.sector is seeded from). A hash-based palette
// (the old approach) doesn't guarantee distinct colors and isn't validated
// for colorblind-safety; a fixed assignment does both by construction.
//
// Validated with the dataviz skill's scripts/validate_palette.js against
// this app's real chart surfaces (frontend/src/index.css --color-surface):
// light #EDF0F7, dark #161616. All 10 slots pass lightness band, chroma
// floor, and CVD (colorblind) separation in both modes -- re-run the
// validator for both --mode light and --mode dark before changing any hex
// value here.
const SECTOR_COLOR: Record<string, string> = {
  oil_gas: '#E85D4C',
  banking: '#4A90D9',
  auto: '#C97F0E',
  it: '#12A08C',
  pharma: '#9B7EDE',
  fmcg: '#3E9B5C',
  metals: '#A0522D',
  telecom: '#D4708C',
  infra: '#6C8CD5',
  other: '#557C30',
};

// Same validated hex as `other` -- an unrecognized sector renders identically
// to the explicit "Other" bucket rather than introducing an unvalidated color.
const FALLBACK_COLOR = SECTOR_COLOR.other;

export function sectorColor(sector: string): string {
  return SECTOR_COLOR[sector] ?? FALLBACK_COLOR;
}
