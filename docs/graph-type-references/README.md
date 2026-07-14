# Graph Type Reference Mockups

Reference mockups the user shared (2026-07-14) showing the visual/structural style of
each graph type from the master spec. These are text-diagram wireframes (not final
UI) meant to convey structure and information hierarchy, not literal pixel design.
The user asked for "much better UI, much better insights, much better aesthetic,
much better functionality" than these mockups — these are a starting reference for
*information content*, not a visual target to copy.

User's star ratings (from the mockup doc, out of 5):
- **Impact Tree — 5 stars, marked "My favorite"**
- Ripple Effect Graph — 5 stars
- Supply Chain Graph — 5 stars
- Timeline Tree — 5 stars
- (Multi-Level Impact Tree, Confidence Tree, Positive/Negative Split, Sector Tree,
  Economic Chain, Knowledge Graph — unrated in the doc, but all requested)

## Files

| File | Graph type | Notes |
|---|---|---|
| `01-impact-tree.png` | Impact Tree | User's favorite. News → Event → Primary Winners/Losers → Secondary Effects → Long-term Effects, expandable branches. |
| `02-ripple-effect-graph.png` | Ripple Effect Graph | News → intermediate node (e.g. "Steel Prices ↑") → fan-out to affected companies. Every node carries confidence, impact score, reason. Described as "how Bloomberg Terminal-style systems visualize relationships." |
| `03-supply-chain-graph.png` | Supply Chain Graph | Linear upstream→downstream chain (Oil Price → Refineries → Chemical Cos → Paint Cos → Automobile Cos → Tyre Cos). "Now users understand *why* the effect propagates." |
| `04-multi-level-impact-tree-a.png`, `04-multi-level-impact-tree-b.png` | Multi-Level Impact Tree | 5 fixed levels (Direct → Supplier/Customer → Competitor → Sector-wide → Macro Economy) replacing the simpler Primary/Secondary split. Worked example: Apple → TSMC/Foxconn/Qualcomm → Samsung/Google → Semiconductor ETFs → NASDAQ. |
| `05-confidence-tree.png` | Confidence Tree | Same news → company chain, but every company shows an explicit confidence % (e.g. NVIDIA 98%, AMD 91%, Intel 72%, TSMC 67%, Dell 42%). |
| `06-positive-negative-split.png` | Positive/Negative Split | Two branches (Positive / Negative), companies listed under each. |
| `07-timeline-tree.png` | Timeline Tree | Fixed horizon buckets (Immediately → 1 Week → 1 Month → Quarter → Year). Worked example: Fed cuts rates → Banks → Housing → Construction → Cement → Infrastructure. |
| `08-sector-tree.png` | Sector Tree | Two-level: News → sector list (Energy → Oil → Gas → Renewables → Utilities), then drill into a sector → its companies (Oil → Reliance → ONGC → IOC). |
| `09-economic-chain.png` | Economic Chain | Macro transmission chain: News → Interest Rates → Inflation → Consumer Spending → Retail → Banks → Technology. |
| `10-knowledge-graph.png` | Knowledge Graph | Not a tree — a graph. Oil Price ← Crude Supply Disruption ← News Event, fanning out to multiple companies (Reliance/ONGC/Oil India), each with its own downstream chain (e.g. Reliance → Petrochemicals → Paint Companies → Asian Paints). Edge types: Supplier, Competitor, Customer, Imports, Exports, Regulation, Commodity, Ownership, Geography, Correlation. User's notes call this "the best long-term approach... becomes extremely powerful over time."

## Data shape the user wants per company (from their notes)

```json
{
  "company": "Tata Steel",
  "impact": "Positive",
  "impact_level": 1,
  "confidence": 96,
  "reason": "Import tariffs improve domestic pricing power.",
  "effect_type": "Direct",
  "sector": "Steel",
  "time_horizon": "Short-term"
}
```

This is richer than what `AlertCompany` currently stores — no numeric `confidence`
(0-100), no `impact_level` (1-5), no explicit `time_horizon`, no `effect_type`
distinct from `basis`. See `docs/superpowers/specs/2026-07-14-charts-page-v3-design.md`
for the earlier scoping discussion of which of these need new backend/LLM work
vs. which are derivable from existing data.
