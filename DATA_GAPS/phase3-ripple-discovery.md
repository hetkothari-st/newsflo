# DATA GAPS — Phase 3 — ripple discovery

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

---

## 7. Phase 3 — the ripple machinery has no economy to run on — OPEN

Phase 3 built discovery, the causal graph, the input-output bootstrap, the
reverse event study and the coverage audit harness. Every one of them works.
Not one of them has any data.

The addendum's own model of the problem is
`ripple_recall ≈ V × M × C × G`, and the coverage harness now MEASURES each
axis separately. Run against this repo today it reports, for every shock
class in the map, the same answer: **V passes, M passes on the fixture graph
and is empty in production, C is zero, G is never reached.** That is the
honest state, and it is now a number rather than a feeling.

| What exists | What is missing | Owner |
|---|---|---|
| `config/exposure_tags.yaml` — 25 tags, closed, DB-enforced | nothing; this is the one Phase 3 artefact that is complete | — |
| `mechanism_edge` schema + BFS walk + review queue | **every edge.** The table is empty in production. The ~60–100 hand-authored FX / rate / realization / regulatory edges have no substitute and never will | repo owner |
| IO parser + Leontief inverse + prune + candidate-edge emitter | **the published tables.** MOSPI Supply-Use / Input-Output Transaction Tables and RBI KLEMS are not in this repo. `io_coefficient` is empty and stays empty | repo owner |
| `config/industry_mapping.yaml` shape | **the mapping itself.** Ships with `_example: true` rows the loader REFUSES. Deciding which listed industry an IOTT code refers to is domain judgement | repo owner |
| `gap_finder.py` — CAR, aggregation, sign test, ranking, persistence | **8+ years of daily returns for the listed universe**, and a dated list of historical instances per shock variable. The module never fetches (an ast scan enforces it), so both are acquisition work | repo owner |
| coverage harness + per-axis diagnostic | **the expected-ripple map.** `tests/coverage/fixtures/expected_ripple_map.yaml` is headed `PROPOSED-PENDING-OWNER-SIGN-OFF`, has four shock classes rather than the twelve to fifteen A6.1 asks for, and `signed_off_by` is `null` | repo owner (domain expert) |
| `exposure_index` view + threshold walk | **the ledger rows underneath it** (§5). The index over an empty ledger returns nothing, so MECHANISM discovery finds nothing, so every ripple family is a C-axis gap | repo owner |

### Sub-gaps recorded with it

* **The recall and precision numbers in the Phase 3 report are measured on a
  SYNTHETIC universe** (`tests/coverage/fixtures/synthetic_universe.json` —
  fake companies, round-number exposures). They prove the harness's
  arithmetic. Real ripple recall today is **0**, for every family, because C
  is zero. **Owner: repo owner** (ledger population, §5).
* **The Leontief toy verification is PENDING OWNER VERIFICATION.** The
  hand-computed inverse is written out in full at
  `.superpowers/sdd/2026-08-17-v5-session0/phase3-leontief-toy.md`; the code
  agrees with it and an independent `(I−A)·(I−A)⁻¹ = I` check runs in CI, but
  no human has checked the cofactor arithmetic. **Owner: repo owner.**
* **IO tables generate INPUT_COST and DEMAND edges only** (A2.4). They
  produce no REVENUE_REALIZATION, FX, rate or regulatory edge, and the
  module refuses to claim otherwise. The hand-authored set is the only route
  to those channels. **Owner: repo owner.**
* **Family membership is `companies.sub_sector`.** The harness decides which
  family a company belongs to by its sub-sector slug. That column is written
  by two different jobs and manual repairs revert (see the repo's own notes),
  so the mapping from ripple family to listed universe is not yet a stable
  artefact. **Owner: repo owner.**
* **Discovery is not wired to the live pipeline.** `discover()` is invoked
  with explicit shocks in tests; nothing constructs a `DiscoveryShock` from a
  real article yet, because event → shock extraction is not this phase. The
  V4 discovery path is untouched and is still what serves. **Owner: V5
  serving phase.**
* **The two A5.1 gate rules are deployed FAIL-OPEN today** —
  `unknown_materiality_delta_passes` and `unknown_sector_proxy_passes` are
  both `true` in `config/gates.yaml`. See the **V5 SERVING CUTOVER CHECKLIST**
  below; this is item 1 there, not a note here. **Owner: V5 serving phase.**
* **`coverage_gap` is empty and its UI page says so.** `/graph/gaps` renders
  "the reverse event study needs price history the repo does not have"
  instead of an empty table pretending to be a clean bill of health.

### The one table Phase 3 populates, and why it is not a breach

`valid_exposure_tag` is written by migration 0013 from
`config/exposure_tags.yaml`. It is **controlled vocabulary, not data**: a tag
name asserts that "tyres buy synthetic rubber" is a concept the schema can
express, and asserts nothing about any tyre maker, any coefficient or any
filing. The claim that a specific company carries an exposure still lives in
`company_exposure`, which still ships empty and is still filled only by a
human approving a verbatim excerpt.
`tests/phase3/test_no_fixture_data_reaches_production.py` asserts that a
migrated database's `valid_exposure_tag` contains exactly the YAML rows and
nothing else, and that `mechanism_edge`, `io_coefficient` and `coverage_gap`
are empty.
