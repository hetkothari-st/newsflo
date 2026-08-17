# DATA GAPS — Proposed spec amendments

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

---

### 9.9 PROPOSED SPEC AMENDMENTS (§7.2 form required) — OPEN

Changes Phase 5 believes the spec should make, recorded rather than
implemented. **None of these is in the code.** EXECUTION_CONTRACT §7.2
requires a *failing measurement* to amend a frozen value, and each entry below
names the measurement that does not yet exist.

**PROPOSED SPEC AMENDMENT 1 — admit `WEAK` to
`primary.allowed_empirical_status`.**

* *Current normative value:* BUILD_SPEC §7.4 — `{AGREE, NO_DATA}`, frozen by
  EXECUTION_CONTRACT §7.1. Deployed unchanged in `config/gates.yaml`.
* *Proposed value:* `{AGREE, NO_DATA, WEAK}`.
* *Argument:* §10.2 defines `WEAK` as "the sample exists but is not
  significant either way" — the same information content as `NO_DATA`, which
  §7.4 already admits at PRIMARY. As frozen, a company we HAVE measured and
  found inconclusive publishes strictly worse than a company we have never
  measured: running the event study can only ever demote a candidate, never
  confirm one. That is a perverse incentive against building the very matrix
  §10.1 asks for, and it lets an insignificant historical sample veto a
  fundamental read.
* *Counter-argument (why the freeze may be right):* precision-first. Until
  the matrix exists nobody knows how many PRIMARY candidates would carry
  `WEAK`, and if the answer is "most of them" the amendment is a large,
  unmeasured loosening of the strongest tier.
* **Missing prerequisite:** a failing measurement. `transmission_empirical`
  is EMPTY (§9.1–9.3), so no candidate has ever carried `WEAK` in anger and
  the precision/recall cost of either choice is unmeasured. The measurement
  becomes possible the day the matrix is populated: count PRIMARY-eligible
  candidates by empirical status, and compare expert-judged precision of the
  `WEAK` group against the `NO_DATA` group.
* *Blast radius if adopted:* one line in `config/gates.yaml`, one assertion
  in `tests/phase3/test_ripple_gates.py`, one in
  `tests/phase5/test_empirical_check.py`. Nothing structural.
* **Owner: repo owner** (spec amendment), after Phase 7's corpus.

**PROPOSED SPEC AMENDMENT 2 — an econometric exposure route
(`measurement = 'ECONOMETRIC'`).**

Raised 2026-08-17 out of the crude bootstrap's coverage failure (§14). Full
§7.2 form, both sides of the argument, and the identification problems:
`docs/v5/amendments/AMENDMENT-002-econometric-exposure.md`.

* *Summary:* estimate exposure by regressing a company's quarterly
  gross-margin ratio on the relevant commodity price; the coefficient is the
  net elasticity after pass-through and hedging, the standard error is the
  band.
* *Recommendation: REJECT AS PROPOSED.* `ROOT CAUSE AXIS = data`, and §7.2
  rejects on that alone. Three substantive objections behind the procedural
  one: it needs a LARGER dataset than the one that just failed
  (`company_financials` has 0 rows); putting a net elasticity in
  `share_of_base` silently double-discounts pass-through inside the §5.1
  formula; and fitting exposures from history collapses Phase 5's
  independence as a cross-check.
* *Redirect, which is the part worth acting on:* the same machinery aimed at
  `pass_through_curve` rather than `company_exposure`. That table's
  `basis = ESTIMATED` and its `curve_needs_review` CHECK already exist, so it
  needs no amendment — and pass-through, not exposure share, is now the
  binding constraint (see §5, "The first eleven rows").
* **Owner: repo owner** (disposition). **Nothing is implemented.**
