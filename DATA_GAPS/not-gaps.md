# DATA GAPS — Not gaps

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

---

## Not gaps

Transmission coefficients and empirical calibration tables (`docs/v5` Phases
4–5) are **not listed here yet** — those phases have not started and their
tables do not exist. They join this file when their schemas land, per the
fabrication guard.

Phase 0 created **no** financial data: it touched no exposure, coefficient or
empirical table, and the only row any Phase 0 migration writes is the
reducer-version fence (`supported_version('r5.0.0')`), which is policy, not
data about the world.

Phase 2 created **no** financial data either. It adds no table and no
migration; `backend/config/materiality.yaml` contains thresholds, band widths
and draw counts and **no parameter value** (a test asserts the only section
naming parameters is `param_bounds`, whose every entry is a `[0, 1]` domain
bound). Every numeral in `backend/tests/phase2/fixtures/` sits inside an
object marked `"_fixture": true`, and
`tests/phase2/test_no_fixture_data_reaches_production.py` asserts no module
under `app/`, `tools/` or `scripts/` can reach it and that the ledger tables
are empty in a freshly built database.

Phase 3 created **no** financial data either. Migration 0013 writes exactly
one kind of row — the controlled vocabulary, explained in §7 — and nothing
else; `mechanism_edge`, `io_coefficient` and `coverage_gap` are empty in a
freshly migrated database and a test asserts it. `config/discovery.yaml`
contains thresholds and a list of economic variable NAMES;
`config/industry_mapping.yaml` contains examples the loader refuses to load.
No input-output coefficient, elasticity, or industry mapping was written from
anybody's knowledge, and a test scans `app/graph/io_bootstrap/` for
coefficient literals.

Phase 1 created **no** financial data either. Migration 0012 writes zero
rows. `backend/config/freshness.yaml` contains policy numbers (how old a
disclosure may be before it is distrusted) and no company facts, and
`tests/phase1/test_ledger_schema.py` asserts it names no company and no
financial figure. Every numeral in `tests/fixtures/phase1/` is a
repeated-digit placeholder inside an object marked `"_fixture": true`, and
`tests/phase1/test_no_direct_write.py` asserts no production module can read
those fixtures.
