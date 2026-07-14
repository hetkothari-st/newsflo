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

// Sequential single-hue ramp, light -> dark, for confidence_score (0-100).
// Never a rainbow, never reused for anything but a magnitude/confidence
// scale -- see the dataviz skill's color-formula rules.
//
// Validated with the dataviz skill's scripts/validate_palette.js --ordinal
// (this is a sequential ramp, not a categorical palette -- the categorical
// checks fail a correct ramp by design) against this app's real chart
// surfaces (frontend/src/index.css --color-surface): light #EDF0F7, dark
// #161616. The brief's original candidate values (#C7D2E8..#1F3D7A) FAILED
// the Light-end contrast check in BOTH modes -- the palest step blended
// into the light surface (1.33:1) and the darkest step blended into the
// dark surface (1.73:1), both below the 2:1 ordinal floor. These replacement
// values compress the band (OKLCH L 0.435-0.695, hue ~258, chroma 0.115) so
// both ends clear 2:1: light-end 2.39:1, dark-end 2.26:1. Re-run the
// validator for both --mode light and --mode dark before changing any hex
// value here.
const CONFIDENCE_RAMP = [
  '#6F9EE4',
  '#5C8ACE',
  '#4976B9',
  '#3763A4',
  '#25508F',
];

export function confidenceColor(score: number): string {
  const index = Math.min(CONFIDENCE_RAMP.length - 1, Math.floor(Math.max(0, score) / 20));
  return CONFIDENCE_RAMP[index];
}
