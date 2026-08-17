"""V5 PHASE 4 -- the policy modifier registry (spec §9).

Regulatory and contractual transfer functions, applied DETERMINISTICALLY
after channel computation and before net-effect resolution. Never by a model:
`tests/phase4/test_no_llm_policy.py` ast-scans this package against every
provider module in the repo, and there is nothing here for a model to judge
anyway -- whether a modifier applies is a tag comparison and a date
comparison, and what it does is arithmetic.

  registry.py   what modifiers exist, who owns them, and when they are in force
  state.py      the tracked regime variables, and when they stop being known
  transfer.py   the six transfer functions, as pure functions of floats
  transforms.py the orchestration: channels in, modified channels out

THE REGISTRY SHIPS WITH NO PARAMETER VALUES. `config/policy_modifiers.yaml`
scaffolds the minimum India set (SAED, APM, retail fuel revision state,
excise and VAT, export and import duties, PLI, MSP, sugar quotas, telecom
AGR, banking risk weights) with STRUCTURE ONLY: every parameter is null,
every owner is `OWNER-REQUIRED`, and the loader refuses to activate an entry
in that state. A levy rate produced from a model's memory would be invisible
and wrong, which is the exact failure the master context's fabrication guard
names. See DATA_GAPS.md §8.
"""
