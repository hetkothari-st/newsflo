/* Curated per-category artwork for cards whose publisher blocks photo
   scraping entirely (Reuters/Bloomberg/BusinessWire wire stories) --
   thematic art, deliberately NOT passed off as the story's own photo.
   Keyed by the backend's fixed category taxonomy
   (backend/app/analysis/schemas.py CATEGORIES). Every URL verified live
   (HTTP 200 + visually checked) at pick time; a broken load falls
   through NewsImage's onError chain to the no-image layout. */

const ART: Record<string, string> = {
  oil_gas: 'https://images.unsplash.com/photo-1513828583688-c52646db42da', // refinery pipework
  banking: 'https://images.unsplash.com/photo-1501167786227-4cba60f6d58f', // bank facade
  auto: 'https://images.unsplash.com/photo-1492144534655-ae79c964c9d7', // cars
  it: 'https://images.unsplash.com/photo-1518770660439-4636190af475', // circuit board
  pharma: 'https://images.unsplash.com/photo-1584308666744-24d5c474f2ae', // medicine blisters
  fmcg: 'https://images.unsplash.com/photo-1542838132-92c53300491e', // grocery shelves
  metals: 'https://images.unsplash.com/photo-1504328345606-18bbc8c9d7d1', // welding
  telecom: 'https://images.unsplash.com/photo-1516044734145-07ca8eef8731', // network hardware
  infra: 'https://images.unsplash.com/photo-1541888946425-d81bb19240f5', // construction site
  macro_policy: 'https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3', // market charts
  geopolitics: 'https://images.unsplash.com/photo-1529107386315-e1a2ed48a620', // parliament
  corporate_event: 'https://images.unsplash.com/photo-1497366216548-37526070297c', // office
  market_commentary: 'https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f', // trading screen
  other: 'https://images.unsplash.com/photo-1504711434969-e33886168f5c', // newspapers
};

const PARAMS = '?w=800&q=60&auto=format&fit=crop';

export function categoryArtUrl(category: string): string {
  return (ART[category] ?? ART.other) + PARAMS;
}
