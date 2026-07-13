// Same deterministic hash-to-palette approach as CompanyChip's avatarColor,
// duplicated here (not imported) so this feature's diff stays isolated from
// components other sessions may be mid-editing.
const SECTOR_PALETTE = [
  '#F5A623', // amber
  '#4A90D9', // blue
  '#2DD4BF', // teal
  '#E85D4C', // red-orange
  '#9B7EDE', // violet
  '#5FB878', // green
  '#D4708C', // rose
  '#6C8CD5', // indigo
];

export function sectorColor(sector: string): string {
  let hash = 0;
  for (let i = 0; i < sector.length; i++) hash = (hash * 31 + sector.charCodeAt(i)) >>> 0;
  return SECTOR_PALETTE[hash % SECTOR_PALETTE.length];
}
