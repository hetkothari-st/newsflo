# DEFECT CLAIMS — the `docs/v5/defects/` number ledger

Written ONLY by the coordinator/owner, same discipline as
`docs/v5/MIGRATION_CLAIMS.md`. Sessions READ this at the main-tree absolute
path (`C:\Users\ST269\Desktop\newsflo\docs\v5\defects\CLAIMS.md`), because a
worktree copy may be stale, BEFORE creating any `DEFECTS-NNN-*.md`.

Established 2026-08-17, after `DEFECTS-003` was written by one session while
another was independently working the register. Nothing collided, by timing.

## Namespace 1 — the FILE number (`DEFECTS-NNN`)

| file | topic | raised by | status |
|---|---|---|---|
| `DEFECTS-001-ceat-proof-of-life.md` | CEAT proof-of-life, nine defects | adr-defects session | OPEN |
| `DEFECTS-002-mechanism-edge-review-authority.md` | `derivation` used as authority | genericity / mechanism-review-authority session | **D10 FIXED** 2026-08-17; file retained with postscript |
| `DEFECTS-003-absence-vs-immateriality.md` | absence vs immateriality | (other session, 2026-08-17) | OPEN |
| **004** | — | **UNCLAIMED** — request before use | — |

## Namespace 2 — the DEFECT number (`D1`, `D2`, …) — SEPARATE, AND IT WILL COLLIDE

**`DEFECTS-NNN` numbers files. `DN` numbers defects. They are two different
counters and they do not line up.** `DEFECTS-002` contains exactly one defect
and it is called `D10`, not `D2`. Claiming a file number does NOT claim a
range of D-numbers, and this is where the next collision comes from.

| D-numbers | live in | note |
|---|---|---|
| D1–D9 | `DEFECTS-001` | priority order D5, D1, D2, D3, D4, D6, D7, D9, D8 |
| D10 | `DEFECTS-002` | the writer-side twin of D1–D9's **D2** |
| D11–D13 | `DEFECTS-003` | |
| **D14** | — | **next unclaimed D-number** |

A session raising a new defect claims **both**: a `DEFECTS-NNN` file number if
it is starting a file, and a `DN` range from the row above. Take the D-range
from this table, never from the highest number in the file you happen to be
editing — `DEFECTS-002`'s highest is D10 and `DEFECTS-003`'s is D13, so a
session reading only the former would mint D11 and overwrite live work.

## Rules

- One defect topic per file (protocol §6). Never edit another session's file;
  append a postscript to your own, or raise a new one that cites theirs.
- A file is **not** deleted or renumbered when its defects are fixed. It stays,
  with its status updated and a postscript recording what shipped — the
  register is the record of what was wrong, not a list of open work.
- A claim abandoned is released back to UNCLAIMED here, never silently reused.
- Cross-file defect pairs are normal and should be stated in both files: D2
  (`DEFECTS-001`, reader side) and D10 (`DEFECTS-002`, writer side) are one
  defect with two faces, raised by two sessions on the same day from opposite
  ends.
