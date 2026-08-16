"""V5 canonical core (docs/v5/01_PHASE_0_canonical_truth.md).

The spec's `newsflo/core/*`. Five rules hold for everything in this package:

  1. No LLM call, ever -- not directly, not through an adapter, not
     deferred behind a lazy import (`tests/phase0/test_gates_no_llm.py`).
  2. No import of `app.market.*` -- market price movement may never
     influence a fundamental verdict (`tests/phase0/test_market_isolation.py`).
  3. `signals.py`, `reducer.py`, `gates.py`, `claims.py` and
     `signal_adapters.py` are PURE: standard library only, no disk, no
     network, no clock, no unseeded randomness
     (`tests/phase0/test_reducer_purity.py`).
  4. `config_loader.py` (reads `backend/config/gates.yaml`) and
     `impact_writer.py` (the only writer of `company_impact`) are the two
     deliberately impure modules, and nothing pure may import them.
  5. Phase 0 creates NO financial data. No exposure, coefficient or
     empirical table is touched anywhere in this package.
"""
