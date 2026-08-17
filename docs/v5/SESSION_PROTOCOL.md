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

## 4.1 Launch the suite only when you are done touching the tree

A suite measures the tree **as it is on disk while it runs**, not as it was at
launch. Edit anything during a run — including adding a test file — and the
number describes a state that never existed.

Commit first. Verify `git status --porcelain` is empty. *Then* run. If you must
work during a run, the number is discarded, not caveated.

**Two instances on 2026-08-17, both in one session, both caught only by
accident:**

- A background suite was launched, then a file was edited mid-run to fix a
  defect. Number discarded, re-run clean.
- A background suite was launched, then a new test file was written and
  `pipeline.py` was briefly mutated to arm a tripwire (§7.3). Both passes
  reported **3974**; the clean re-run reported **3979**. The five-test gap is
  the new file, which neither pass had collected — so the run was reporting on
  a tree that did not include work already written to it.

**The tell is the collected count.** A pass/fail line alone cannot show this;
the totals can. If the count moves for a reason you cannot name, the run is
suspect. If it *doesn't* move when you added tests, the run did not see them.

Precedent: the 70-phantom-failure incident (§4). Same mechanism, larger blast
radius — a suite run against a tree another session was saving into. §1 removes
the cross-session version of this; §4.1 covers the version you do to yourself,
which isolation cannot prevent.

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

## 7. Staging discipline (residual backstop)

**§1 is the fix. This section is the backstop for what §1 does not cover.**
Every measured instance of cross-session damage in this repository traces to
sessions sharing one tree, and none of them is reachable from separate
worktrees — there is no shared path for another session's bytes to arrive on.
Careful staging is not an alternative to isolation. It is what you do in the
integration tree, and on the day you discover you were in the wrong one.

Even inside your own worktree: explicit-path staging only. Before committing,
read `git diff --cached` **in full** — not `--stat`. `--stat` reports paths
and line counts and **cannot show authorship**; a commit that carries another
session's edits at a path you legitimately own passes every `--stat` check
(see §7.1). Confirm each hunk is text this session wrote. After committing,
`git show --stat HEAD`.

Never stage: `.superpowers/`, `api_keys.txt`, `*.db`, another session's
files. In the integration tree these rules are absolute.

## 7.1 Never commit a hunk you did not write

`git add <path>` stages the file **as it is on disk**, not as you last wrote
it. In a shared tree those differ whenever another session touched the path in
between, so **owning a path is not evidence that you authored its current
contents**. Explicit-path staging controls *which paths* enter a commit; it
says nothing about *what content is at them*. A session can follow §7 exactly
and still commit another session's work.

This is not hypothetical and it is not rare: three documents on 2026-08-17
were committed by sessions that had not written them, by sessions doing
staging correctly. `docs/v5/protocol/FINDING-001-shared-tree-authorship-carry.md`
is the measurement.

If `git diff --cached` shows a hunk you did not type, do one of:

1. **Preferred** — leave it. `git restore --staged <path>` and let its author
   commit it.
2. **When the file cannot be split** (one document, two authors, and the other
   session has stopped), commit it and **record the carry** with a trailer:

   ```
   Carried-From-Session: <session> <path> (<section or line range>)
   ```

A carry that is recorded is a coordination note. A carry that is not is a
false authorship claim that survives in the log forever. The only thing that
can correct it afterwards is a handover document — which `git log`, `git
blame` and code review never read.

**Why no check catches this automatically.** `--stat` compares paths and line
counts; a preservation audit compares content before and after. Both answer
*what is present*. This defect does not change what is present — it changes
**who put it there**, so a contaminated commit and a clean one are
indistinguishable to either. A mechanical backstop (a pre-commit hook refusing
staged paths whose mtime post-dates this session's last write to them) is
**recorded and deliberately not built**: §1 prevents the whole class, and
building it would imply shared trees are a supported mode. They are not.

## 7.2 A fixture default must never encode the semantics under test

When a guarantee is `X implies Y`, **no fixture, seeder, factory or helper may
derive Y from X.** Derive it and the fixture asserts the rule for free, so the
test can no longer fail when the rule is wrong — the guarantee has moved into
the layer that was supposed to be checking it, where nothing tests it at all.
Make the caller state Y.

The measured case (2026-08-17, defect D10). `mechanism_edge` rows are walkable
iff `review_status = 'APPROVED'` with a non-null `reviewed_by`. The obvious
convenience was for `seed_edge` to default `review_status` to `APPROVED`
**when `reviewed_by` is non-null** — it made three failing tests pass with no
edits. It also *is* the defect: "a reviewer name means approval" was exactly
the conflation being fixed, and putting it in the seeder would have bought a
smaller diff by encoding the bug into the instrument used to detect it. The
seeder now takes `review_status` explicitly and defaults it unconditionally.

**The symptom to watch for is a test that goes GREEN across a semantic
change.** In the same fix, a test named for the old (wrong) rule passed
untouched, because it inherited the new default — it would have been read by
the next session as coverage of a rule it actually contradicted. A red test
announces itself; a test passing for a reason other than the one it names does
not. After changing a rule, look at what **stopped failing that you expected
to fail**, not only at what broke.

This is the second guarantee found living in the wrong layer in one day. The
first was authorship (§7.1: a path you own is not evidence you wrote its
contents). Both were invisible to the checks in place, for the same reason —
the check compared the wrong thing, and comparing the wrong thing produces
silence, not an error.

**See §7.3**, which is this same defect one layer up: a fixture that encodes
the rule (§7.2) makes a test unable to fail *when the rule is wrong*; a guard
that was never armed (§7.3) is unable to fail *at all*.

## 7.3 Every guard test must be proven to fail

**A guard whose failure has never been observed is an assumption.**

A guard test — a tripwire, an invariant pin, a "this must never happen" —
earns nothing by passing. Passing is its resting state. Its entire value is
that it *would* go red, and that is a property nobody has checked until
somebody makes it red on purpose.

**Arm it, and commit the arming proof:**

1. Introduce the violation the guard exists to detect.
2. Observe **red**, and read the failure message — a guard that fires with an
   unreadable message is half-armed.
3. Revert. Confirm the working tree is byte-identical (`git diff` empty, not
   `git status` clean — see the genericity handover on stat-dirty files).
4. Observe **green**.
5. **Put the proof in the commit message**, not only the test: what violation
   was introduced, that it went red, and that the revert was verified. The next
   reader cannot re-derive this from the test body.

**Four instances on 2026-08-17, one shape.** Each is a guard that reads as
coverage while being structurally unable to fire:

| guard | why it could not fail |
|---|---|
| `test_three_tier_policy:235` | green if the registry lookup is deleted outright |
| Phase 6 section fixtures | keyed on `paints_input_cost`, an id the adapters cannot emit — so the fixture exercised nothing |
| `coverage_rows` | returned `None` on every row when its join key drifted; indistinguishable from an empty ledger |
| the §7 cutover tripwire | green on the exact wiring it exists to detect — module names were matched as text, and `from app.output import sections` does not contain `"app.output.sections"` |

The last one is the sharpest, because it was written *by the session that had
already written §7.2 that day*, to guard against this very class, and it
shipped green-and-dead until someone tried to break it. Knowing the failure
mode does not protect you from it. Only arming does.

**Same defect as §7.2, one layer up.** §7.2 is a *fixture* that encodes the
semantics under test, so the test cannot fail when the rule is wrong. §7.3 is a
*guard* that cannot fail at all. Both compare the wrong thing; both produce
silence rather than an error; both read afterwards as evidence they never
were.

**Corollary, from the same day.** After changing a rule, look at what
**stopped failing that you expected to fail** — not only at what broke. A test
that goes green across a semantic change has either been fixed or been
hollowed, and the two are indistinguishable from the summary line.

## 8. What this replaces

The earlier ad-hoc rules ("serial writer", "explicit paths", per-dispatch
no-touch lists) remain good practice inside a worktree but are no longer the
primary defense — isolation is. If you find yourself writing a no-touch list
for a shared tree, you are in the wrong tree.
