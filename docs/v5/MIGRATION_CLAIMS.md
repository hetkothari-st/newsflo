# MIGRATION CLAIMS — the alembic number ledger

Written ONLY by the coordinator/owner. Sessions READ this at the main-tree
absolute path (worktree copies may be stale) BEFORE authoring any migration.
Protocol: `docs/v5/SESSION_PROTOCOL.md` §2.

| revision | status | claimed by | purpose |
|---|---|---|---|
| 0001–0009 | APPLIED | (history) | V4 baseline through fact-provenance |
| 0010–0015 | APPLIED | V5 program (sessions 0–8) | Gate Zero eval tables through empirical/calibration |
| 0016 | APPLIED | genericity session | valid_exposure_tag re-sync (base_oil, bought_in_freight, intermediated_air_capacity) |
| 0017 | **CLAIMED** | merge-integration session | `exposure_coverage` view re-key: GROUP BY `companies.sector` → `official_isubgroup`. DROP VIEW + CREATE VIEW, no table touched, `companies.sector` neither read as a key nor written |
| 0018 | **UNCLAIMED** | — | next available — request before use |

Rules:
- A session needing a migration requests the next UNCLAIMED number from the
  coordinator; the row flips to CLAIMED with the session name before any
  file named `NNNN_*.py` is created.
- Two files claiming one number = the single-head guard fails the suite and
  blocks the merge (`backend/tests/test_migration_single_head.py`).
- A claim abandoned (task cancelled) is released back to UNCLAIMED here,
  never silently reused.
