"""V5 PHASE 5 -- the surprise engine, Axis C (spec §14).

Answers "is this actually news?" -- the first objection any professional
raises, and the one V4 could not answer at all.

THE ONE RULE, AND IT IS STRUCTURAL: **Axis C never alters direction or
materiality.** It is not a fundamental input. It ranks a feed, badges an item
`ALREADY WIDELY REPORTED`, and raises the `ALREADY_PRICED` objection at WARN.
That is the whole of its authority.

The rule is enforced by the IMPORT GRAPH rather than by discipline:
`app/analysis/sensitivity/*`, `app/analysis/policy/*` and `app/core/*` import
nothing from this package, ast-asserted in
`tests/phase5/test_surprise_isolation.py`, which also mutates every surprise
field and checks the canonical record byte-identical either side.

DETERMINISTIC, OFFLINE, CLOCKLESS. Novelty is token-overlap cosine, not an
embedding: no model call, no network hop, and a score anybody can reproduce.
Timestamps arrive as arguments -- nothing here reads a clock, so a latency
number is a measurement rather than a coincidence of when the test ran.

WHAT IS MISSING. There is no consensus feed and no forward-curve feed in this
repo, so `consensus_gap_sigma` and `forward_curve_implied` are None unless a
caller supplies the inputs. None means MISSING; it does not mean zero surprise
(DATA_GAPS §9).
"""
