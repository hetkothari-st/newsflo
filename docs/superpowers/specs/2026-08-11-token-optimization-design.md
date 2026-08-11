# Impact-graph token/cost optimization (2026-08-11, specs: token_optimization + implementation prompt)

## Measured baseline (live, this session, cost-capped build ef69e42)
| Event | Calls | In | Out (incl. thinking) | Latency | Companies |
|---|---|---|---|---|---|
| RBI rate cut | 11 | 39,756 | 25,027 (thinking 8,979) | 231s | 16 verified |
| Unemployment | 18 | 68,577 | 26,010 (thinking 13,549) | 263s | 15 |
| Hormuz (pre-caps) | ~20 | 74,005 | 68,994 | 625s | 53 |
| PLFS (prod) | — | — | — | ~250s | 28 verified |

Stage split (unemployment): map_companies 44.8k in / 13k out over 9 calls;
ripple_discovery 17.7k in / 8.7k out over 7 calls; facts+shocks ~3.5k in.
cached_tokens = 0 on every call (implicit cache never hit).

## Where the tokens actually go → the fix for each
1. **cached_tokens=0**: static prefix rides `systemInstruction`; Gemini
   implicit caching keys on the CONTENTS prefix. FIX: move the static
   prefix into the head of the user content (identical bytes per stage),
   keep systemInstruction minimal. Measure cache hits next live run.
2. **map_companies input**: full facts+evidence block + whole-graph
   outline + 100-char candidate descriptions × 40, repeated per node.
   FIX: compact fact lines (IDs) once; ancestor path of THIS node only;
   compact candidate profile lines (ticker|name|sub_sector|60-char desc);
   cached-exposure block replaces rediscovery (P3).
3. **ripple_discovery input**: whole graph outline + all node ids per
   hop. FIX: ancestor path + sibling ids only; batch same-parent
   frontier nodes (≤3) into one call with per-node children.
4. **Ranking Pro call**: pure bucket assignment. FIX: deterministic
   (net_direction → bucket, code already sorts). Call removed.
5. **Verification output**: per-ticker records. FIX: diff contract —
   accept[] / reject[] / corrections{} — code applies.
6. **Company output**: 6 optional-list fields requested as required.
   FIX: compact contract — ticker/direction/impact/materiality/
   confidence/mechanism/horizon/rationale + net-effect channels; the
   rest optional.
7. **Repeated fundamentals**: (company, economic_node) relationship
   cache, positive AND negative, written from verification results;
   negative → company skipped from that node's candidate list; positive
   → injected as BASE EXPOSURE (event modifier still Gemini-judged);
   invalidated when company metadata is newer than the cache row.
8. **Synonym nodes**: deterministic normalizer (crude_oil_price_up ==
   higher_crude_prices etc.) before registration — duplicate branches
   never reach an LLM.
9. **No-call gates**: existing (candidates/depth/thresholds/visited) +
   new (normalized-mechanism dedup, negative-relationship skip,
   verified-relationship auto-accept) — all logged
   `call_skipped reason=...`.

## Quality additions required by the spec (not cost)
- Net-effect reasoning: positive_channels / negative_channels /
  net_direction (mixed|uncertain valid; relative vs absolute
  beneficiary distinguished) on the company contract; persisted to
  alert_companies.channels_json + net_direction.
- Segment hints: candidate profile lines carry sub_sector + first
  business-desc clause so diversified companies are judged at segment
  level.

## Explicitly NOT done (limitations)
- Incremental per-branch graph updates (story updates reuse the
  content-hash cache / duplicate-alert path; no delta recompute).
- Mechanism template library (doc 1 §7) — normalizer covers dedup; the
  template prior is deferred.
- Cheaper-model verification for low-risk rows — spec forbids without
  benchmark proof; only cache-verified auto-accept implemented.
- Gemini Batch API (offline backfills only; none scheduled).

## Acceptance: rerun RBI + unemployment live; require quality >= baseline
(companies, direction accuracy vs labels) and tokens/cost strictly lower;
report exact numbers.
