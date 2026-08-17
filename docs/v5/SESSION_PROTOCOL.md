# SESSION PROTOCOL — multi-session coordination rules

**Status: BINDING for every Claude/agent session working this repository.**
Read this before touching anything. Established 2026-08-17 after three
measured coordination failures: two shared-index staging races (another
session's files swept into a commit) and one mid-edit suite run (70 phantom
failures measured on a tree another session was saving into).

---

## 1. One worktree per session — never the shared tree

Every session works in its own git worktree under `.worktrees/` (gitignored),
on its own branch. The main checkout at the repo root is the **integration
tree**: it belongs to whichever single session is currently merging, and to
nobody else.

```
git worktree add .worktrees/<session-name> -b wt/<session-name> master
```

- The dev DB (`backend/newsflo.db`) does NOT follow into worktrees (it is
  untracked). The test suite never needs it (conftest builds scratch DBs).
  Manual dev-DB work targets the ONE canonical copy in the main tree and is
  itself serialized: one session at a time, by explicit owner assignment.
- `backend/.venv` does not follow either. Run tests with the main tree's
  interpreter against your worktree:
  `C:\Users\ST269\Desktop\newsflo\backend\.venv\Scripts\python.exe -m pytest`
  from your worktree's `backend/`. Proven working; do not build per-worktree
  venvs without a reason.
- `ENABLE_SCHEDULER=false` in the environment of every test run, always.

## 2. Migration numbers are claimed at dispatch

The next alembic revision number is **assigned before a session starts work**,
never chosen by the session mid-flight. Claims live in
`docs/v5/MIGRATION_CLAIMS.md` **in the main tree** — read it at the absolute
path (`C:\Users\ST269\Desktop\newsflo\docs\v5\MIGRATION_CLAIMS.md`), because
your worktree's copy may be stale. Only the coordinator/owner writes claims.

A session that discovers mid-task it needs an unclaimed migration STOPS and
requests a claim; it does not mint a number.

## 3. Merges to master are strictly serialized

One session merges at a time. The sequence for the merging session:

1. Announce/obtain the merge slot (owner or coordinator grants it).
2. Rebase or merge `master` into your branch **in your worktree**; resolve
   there.
3. Run the FULL suite in **your own worktree** on the merged result.
4. Merge to `master` (fast-forward preferred; merge commit otherwise).
5. Run the single-head migration guard + full suite once more if anything
   about the merge was non-trivial.
6. Release the slot.

## 4. The only reportable suite number

**Never report a suite number from a tree another session may be editing.**
A number is reportable only when produced in a worktree (or the integration
tree during an exclusively-held merge slot). The 70-phantom-failure incident
is the precedent: a mid-edit tree produces numbers that are noise in both
directions, and a clean re-run afterward is luck, not evidence.

## 5. The single-head guard is a merge precondition

`backend/tools/migrate_on_boot.py` asserts the alembic script directory has
exactly one head (fifth boot backstop), and
`backend/tests/test_migration_single_head.py` enforces it in the suite. A
merge that produces two heads fails both. Do not resolve a fork by renaming
someone else's migration — take it to the coordinator; the claim ledger
exists so this never happens.

## 6. Shared documents are per-topic, append-preferred

- `DATA_GAPS.md` is a pure index. Gaps live in `DATA_GAPS/<topic>.md` —
  one topic per file. Add a gap = add a topic file (or append to YOUR
  topic's file) + one index line. Never rewrite another topic's file.
- Same pattern for decision records (`docs/v5/decisions/ADR-NNN-*.md`,
  one file per decision, never edited after acceptance) and amendments
  (`docs/v5/amendments/`).
- Reports/ledgers under `.superpowers/` are per-session and untracked.

## 7. Staging discipline (defense in depth)

Even inside your own worktree: explicit-path staging only, verify
`git diff --cached --stat` before commit and `git show --stat HEAD` after.
Never stage: `.superpowers/`, `api_keys.txt`, `*.db`, another session's
files. In the integration tree these rules are absolute.

## 8. What this replaces

The earlier ad-hoc rules ("serial writer", "explicit paths", per-dispatch
no-touch lists) remain good practice inside a worktree but are no longer the
primary defense — isolation is. If you find yourself writing a no-touch list
for a shared tree, you are in the wrong tree.
