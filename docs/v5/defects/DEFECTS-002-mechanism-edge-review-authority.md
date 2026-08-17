# SPEC DEFECTS 002 — `derivation` is doing `review_status`'s job

**Raised:** 2026-08-17 · **Status:** OPEN, nothing fixed, nothing inserted · **Owner:** repo owner
**Evidence:** the five fertilizer candidates in `backend/config/mechanism_edges_authored.yaml` (authored, **not loaded**) · `DATA_GAPS/fertilizer-complex.md` §15
**Pairs with:** `DEFECTS-001-ceat-proof-of-life.md` **D2**. Same hole, opposite side.

**Rule for this document:** it describes a defect and the shape a fix must
have. No fix is implemented and none should be written against it until the
owner has read it. It is a separate file from DEFECTS-001 only to avoid two
sessions editing one document; D2 and D10 below are one defect with two
faces and should be fixed in one change.

| # | Defect | Layer | Severity |
|---|---|---|---|
| **D10** | `derivation` records who WROTE a row; the traversal gate reads it as who CHECKED it | **schema + graph walk** | **Highest writer-side defect. With D2 the §A3.2 guarantee is enforced by nothing at either end.** |

---

# D10 — Provenance is being used as authority

## What is wrong

`mechanism_edge.derivation` is a **self-declared provenance string** — it
says what kind of thing produced the row. `app/graph/traverse.py::usable()`
reads it as an **authorisation**:

```python
if str(row["review_status"]) == "REJECTED":
    return False
if str(row["derivation"]) in REVIEW_REQUIRED_DERIVATIONS:   # IO_TABLE, EMPIRICAL
    return bool(row["reviewed_by"])
return True                                                  # <- AUTHORED, always
```

So a row inserted with `derivation = 'AUTHORED'`, `review_status = 'PENDING'`,
`reviewed_by = NULL` is **live on traversal the moment it lands**, and
`app/ledger/edge_review.py::pending_edges` selects
`derivation IN ('IO_TABLE','EMPIRICAL')` — so it **never appears in any
queue** either. There is no state in which such a row is both inert and
visible to a reviewer. It is either live, or it does not exist.

The columns to do this correctly already exist and are unread by the walk:
`review_status`, `reviewed_by`, `reviewed_at`.

## How it was found

An instruction to author five fertilizer mechanisms as candidates —
`derivation=AUTHORED`, `reviewed_by NULL`, "queued for my approval via
`edge_review`" — turned out to be **unsatisfiable as stated**, in two
independent ways:

1. AUTHORED rows are excluded from `pending_edges` by its `derivation`
   filter, so they cannot be queued;
2. AUTHORED + PENDING is walkable, so inserting them would make them live,
   not queued.

The five were written to `backend/config/mechanism_edges_authored.yaml` and
**not inserted**. They are blocked on three separate content gaps besides
(§15), so nothing shipped either way — but the schema hole is real
independently of them.

## Why this is the same defect as D2

| | D2 (reader side) | D10 (writer side) |
|---|---|---|
| where | `gates.yaml::require_mechanism_id` → the SECONDARY gate | `traverse.usable()` → the graph walk |
| what it checks | that `mechanism_id` is a non-null **string** | that `derivation` is not one of two **strings** |
| what it should check | that the id resolves to a row in an approved state | that the row is in an approved state |
| result | an unreviewed edge **publishes** | an unreviewed edge is **walkable and unqueued** |

D2 says the gate never asks whether the mechanism was reviewed. D10 says the
walk asks the wrong column. Fix either alone and the guarantee still leaks
through the other: an edge that cannot be walked cannot publish (D10 alone
would close the practical path), but a `mechanism_id` naming an approved-then-
rejected or non-existent row still passes D2's rule. **Both, in one change.**

`NEWSFLO_V5_ADDENDUM_RIPPLE_COVERAGE` §A3.2's "mechanism reviewed & authored
as edge → companies tagged → now publishable" is, today, enforced at neither
end.

---

## THE OWNER'S PROPOSED FIX, ARGUED

> - add `derivation = 'MODEL_PROPOSED'` — these five are that, not AUTHORED
> - `pending_edges` filters on `review_status = 'PENDING'`, not on `derivation`
> - `traverse.usable()` requires `review_status = 'APPROVED'` for every
>   derivation except genuine human AUTHORED

**Three of four: correct. The exception in the fourth is the defect
restated rather than fixed, and it should not exist.**

### (a) `MODEL_PROPOSED` — agreed, and it is the honest label

These five were proposed by a model and transcribed into a file. Calling
that AUTHORED overstates it. Add it.

But add it as **provenance for a reader**, not as an input to any decision.
See (c).

### (b) `pending_edges` on `review_status` — agreed, unreservedly

This is the strictly better rule and it needs no exception. A queue keyed on
"what state is this in" answers the question a reviewer is asking; a queue
keyed on "what kind of thing made this" cannot, and today silently omits an
entire derivation.

**One test's assertion inverts under this change and should:**
`tests/phase3/test_io_bootstrap.py::test_an_unreviewed_io_edge_appears_in_the_review_queue`
seeds an `IO_TABLE` edge and an `AUTHORED` edge, both with `reviewed_by=None`,
and asserts the queue contains **only** the IO one. Under the fix it must
contain both. That test currently pins the defect.

`edge_review.edge_queue_stats` carries the same `derivation IN
('IO_TABLE','EMPIRICAL')` filter in its `pending` count and must move with it,
or the console will report a queue depth smaller than the queue.

### (c) The AUTHORED exception — argued against

**`derivation` is written by whoever inserts the row. It cannot be a
security boundary.**

If AUTHORED skips review, then the rule is: *anything that can write the
string `'AUTHORED'` can authorise its own edge.* That is the defect, with an
extra enum value in front of it. `MODEL_PROPOSED` helps a writer that is
trying to be honest; it does nothing about a writer that is careless, or one
whose helper defaults to the wrong value.

That is not hypothetical. **This repo's own edge seeder already defaults to
it:**

```python
# tests/phase3/conftest.py
def seed_edge(session, *, edge_id, ..., derivation: str = "AUTHORED", ...)
```

`AUTHORED` is what you get by not thinking about it. A default that also
means "skip review" is a trap, and the five fertilizer rows walked straight
into it.

**The stated justification does not survive the new enum either.**
`traverse.py`'s docstring argues:

> An AUTHORED edge was written by a person in the first place, so there is no
> second person for it to be waiting on; `review_status` on it records a
> later re-review, not its birth.

Once `MODEL_PROPOSED` exists, that sentence is *true of correctly-labelled
AUTHORED rows and irrelevant*: a person who authored an edge can set
`review_status='APPROVED'` and `reviewed_by='human:<name>'` in the same
insert. That is one extra field, at the moment they are already typing the
row, and it converts a self-declared category into a recorded signature.
The guarantee becomes uniform and reads the same for every derivation:

> **A row is walkable iff a named human approved it.**

Nothing about that is harder for a genuine human author. It is only harder
for a writer that wanted to skip the step.

**Recommendation:**

```python
def usable(row) -> bool:
    if str(row["review_status"]) == "REJECTED":
        return False
    return (str(row["review_status"]) == "APPROVED"
            and bool(row["reviewed_by"]))
```

No `derivation` read at all. `REVIEW_REQUIRED_DERIVATIONS` is deleted, not
extended. `approve_edge` already writes exactly this pair
(`review_status='APPROVED'`, `reviewed_by=<reviewer>`), so no new machinery
is needed — the approval path already produces the state the walk would
require.

Consider also moving the condition into `traverse._SELECT`, which today
filters only `review_status <> 'REJECTED'`. One rule, in SQL, index-friendly,
and impossible to bypass by calling `traverse` without `usable`.

**If the owner keeps the exception anyway**, then at minimum it must be
narrowed to `derivation='AUTHORED' AND reviewed_by IS NOT NULL` — a signature
rather than a category — and `MODEL_PROPOSED` must be barred from ever being
updated to `AUTHORED` by anything but a human review action. That is more
moving parts than deleting the exception, for a weaker guarantee.

---

## WHAT IT BREAKS — MEASURED, NOT ESTIMATED

Each variant patched into `traverse.usable()` in memory and the graph,
discovery, coverage, genericity, policy, sectioning and eval suites run
(583 tests). `traverse.py` restored byte-identical after each.

| variant | result |
|---|---|
| **current (deployed)** | 583 passed |
| **owner's proposal** — APPROVED required, AUTHORED exempt | **1 failed** |
| **strict** — APPROVED + `reviewed_by` for every derivation | **26 failed** |
| **strict + 3 fixture seeders emitting `review_status='APPROVED'`** | **3 failed** |

### The IO_TABLE path: exactly one test, and its premise is the defect

Under **both** variants, the single IO_TABLE failure is:

```
tests/phase3/test_discovery_sources.py::test_a_reviewed_io_table_edge_can_be_traversed
```

```python
seed_edge(..., derivation="IO_TABLE", reviewed_by="human:fixture-reviewer",
          io_total_coeff=0.31)          # review_status defaults to PENDING
edges = traverse(...)
assert [e.edge_id for e in edges] == ["e-io2"]
```

It seeds `reviewed_by` **without** `review_status='APPROVED'` and expects
traversal — i.e. it pins the current rule that *a non-null reviewer name is
approval*. That is D2's conflation on the writer side. Under any fix the test
must seed an approved edge. **This is the one genuinely semantic test change
in the whole set.** The IO_TABLE path itself is otherwise unaffected:
`io_bootstrap/load.py` already writes `reviewed_by=NULL` and refuses anything
else, `approve_edge` already writes the approved pair, and
`test_an_empirical_edge_without_a_reviewer_cannot_be_traversed` passes
unchanged under every variant.

### The other 25 are three fixture builders missing one field

No test in this repo sets `review_status` anywhere. Every seeded edge is
`PENDING`, and 25 of the 26 strict failures are fixtures that expect
traversal from a PENDING row. Adding `review_status='APPROVED'` to three
seeders takes 26 → 3:

* `tests/phase3/conftest.py::seed_edge`
* `tests/coverage/conftest.py::_insert_edge`
* `tests/genericity/test_synthetic_shock_genericity.py::_seed`

The remaining 3 are an artefact of that blunt patch, not breakage — it forced
`APPROVED` onto edges the review-queue tests deliberately want `PENDING`
(`test_an_unreviewed_io_edge_appears_in_the_review_queue`,
`test_the_queue_is_ranked_by_coefficient`,
`test_approving_an_edge_records_the_reviewer`). The correct seeder takes
`review_status` as a parameter defaulting to `APPROVED`, and those three pass
`PENDING`.

**So the true cost of the strict variant is: 3 seeder signatures, 1 test with
a wrong premise, and 1 test assertion that inverts by design.** Not 26.

### Nothing in production changes

`mechanism_edge` ships empty (§7) and is empty in every database checked. No
serving path reads it. The blast radius today is fixtures.

---

## ACCEPTANCE TEST

The owner's stated test, made precise:

> With the fix in place, inserting these five must NOT make them traversable
> until I approve each one.

```python
def test_a_model_proposed_edge_is_inert_until_a_human_approves_it(session):
    seed_edge(session, edge_id="fert-1", from_node="FERTILIZER_SUBSIDY_OUTLAY",
              to_node="fertilizer_subsidy_receivable",
              exposure_tag=TAG_SUBSIDY_REALIZATION,
              derivation="MODEL_PROPOSED", reviewed_by=None,
              review_status="PENDING")

    # 1. inert on the walk
    assert traverse(session, "FERTILIZER_SUBSIDY_OUTLAY", as_of=TODAY) == ()

    # 2. and VISIBLE, which is the half the current schema cannot express
    assert [r["edge_id"] for r in pending_edges(session)] == ["fert-1"]

    # 3. approval, by a named human, is what makes it walkable
    approve_edge(session, "fert-1", reviewed_by="human:owner")
    assert [e.edge_id for e in
            traverse(session, "FERTILIZER_SUBSIDY_OUTLAY", as_of=TODAY)] == ["fert-1"]
```

Step 2 is the part worth insisting on. "Inert" alone is satisfiable by
dropping the row on the floor; the defect is that today there is no state
which is *both* inert and queued.

Add the same three steps with `derivation="AUTHORED"` and no reviewer. Under
the recommended fix they read identically — which is the point of removing
the exception, and is the assertion that would have caught this.

Pair with D2's own acceptance test (the CEAT run must **stop publishing**
until its two edges are approved). Both should be in the same change.

---

## OUT OF SCOPE HERE

* The five fertilizer edges stay in
  `backend/config/mechanism_edges_authored.yaml`, unloaded. They are blocked
  on three content gaps (§15) as well as on this schema hole.
* No exposure leaf, no shock variable, no table row was added. `derivation`
  is unchanged, `usable()` is unchanged, `pending_edges` is unchanged.

---

# POSTSCRIPT — what the fix actually cost, measured after the fact

**Added 2026-08-17 by the merge-integration session. Nothing above is edited.**
D10 is FIXED as of this postscript. The body is left exactly as raised,
including the cost estimate this postscript corrects, because a defect register
that quietly updates its own predictions stops being evidence of anything.

## The count was 5 sites. It was 7.

The body states: *"the true cost of the strict variant is: 3 seeder signatures,
1 test with a wrong premise, and 1 test assertion that inverts by design. Not
26."* Measured against the implemented fix:

| site | predicted | actual |
|---|---|---|
| `tests/phase3/conftest.py::seed_edge` | yes | signature gains `review_status="APPROVED"` |
| `tests/coverage/conftest.py::_insert_edge` | yes | SQL literal |
| `tests/genericity/…::_seed` | yes | SQL literal |
| `test_an_unreviewed_io_edge_appears_in_the_review_queue` | yes, inverts | `["io-1"]` → `["io-1", "auth-1"]` |
| `test_a_reviewed_io_table_edge_can_be_traversed` | yes, wrong premise | see below — **it did not fail** |
| `test_the_queue_is_ranked_by_coefficient` | **no** | needs explicit `review_status="PENDING"` |
| `test_approving_an_edge_records_the_reviewer` | **no** | needs explicit `review_status="PENDING"` |

## Why the two extra appeared — the prediction was shaped by the measuring instrument

The body dismisses those two: *"The remaining 3 are an artefact of that blunt
patch, not breakage… The correct seeder takes `review_status` as a parameter
defaulting to `APPROVED`, and those three pass `PENDING`."*

That second sentence contains its own refutation. **"Those three pass
`PENDING`" IS the edit.** Once the seeder's default is `APPROVED`, a fixture
wanting a row awaiting review must say so — three call sites change, one of
which was already counted separately for its inverting assertion. So two sites
were predicted as "not breakage" and are in fact edits, of the smallest kind.

The prediction was an artefact of the blunt patch in the same way the failures
were. Variants were measured by patching `usable()` in memory and running; a
blunt patch cannot distinguish *"this test breaks"* from *"this test now needs
an argument it never passed"*, because both surface identically as a red line.
Separating them required writing the seeder, which the measurement deliberately
did not do. The error is small and in the honest direction, and it is recorded
because a cost table that was right about 26→3 and wrong about 3→5 is more
useful with both halves visible.

## The finding worth more than the count: a test went GREEN and should not have

`tests/phase3/test_discovery_sources.py::test_a_reviewed_io_table_edge_can_be_traversed`
is named in the body as *"the one genuinely semantic test change in the whole
set"*. Under the implemented fix it **passed without being touched.**

It seeds `reviewed_by="human:fixture-reviewer"` and no `review_status`. Once
the seeder defaulted to `APPROVED`, the row came out approved-and-signed, the
test traversed it and went green — while still being named for, and structured
around, the proposition that *a non-null reviewer name is approval*. That
proposition is defect D2. A test asserting the defect would have survived the
fix silently and been read by the next session as coverage of it.

A failing test announces itself. A test that passes for a reason other than the
one it claims does not — and the D2/D10 pair is exactly this class of error one
layer down: a guarantee living in a column nothing checked.

Fixed by making both fields explicit, renaming to
`test_an_approved_io_table_edge_can_be_traversed`, and adding the assertion
whose absence let the conflation stand:
`test_a_named_reviewer_alone_does_not_make_an_edge_traversable` — a PENDING row
WITH a reviewer name must not traverse, and must appear in the queue.

## The tempting shortcut that was rejected

Defaulting `review_status` to `APPROVED` **only when `reviewed_by` is
non-null** makes all three queue tests pass with no edits at all. Rejected:
that rule is "a reviewer name implies approval", which is D2 itself, relocated
into the fixture layer where no test can see it. It buys a smaller diff by
encoding the defect into the tool used to test for the defect.

**Generalised into protocol rather than left in a commit message:** a fixture
default must never encode the semantics the fixture exists to test —
`docs/v5/SESSION_PROTOCOL.md` §7.2.

## What shipped

`usable()` reads no `derivation`; `REVIEW_REQUIRED_DERIVATIONS` deleted, not
extended; the same condition pushed into `traverse._SELECT` so it cannot be
bypassed; `pending_edges` and `edge_queue_stats` keyed on `review_status`
alone; `derivation = 'MODEL_PROPOSED'` added as provenance, read by no
decision; the five fertilizer candidates relabelled. `pending_edges` also lost
its `reviewed_by IS NULL` clause — a named-but-PENDING row would otherwise have
been inert AND invisible, which is D10 one column over.

Suite: **3966 passed, 10 skipped, 2 failed** — both failures pre-existing and
unrelated (`docs/v5/KNOWN_BREAKAGE.md` KB-001).

Open question 1 in the genericity handover — *"D10: does the AUTHORED exception
survive?"* — is answered: **no.** Deleted, not narrowed.

## What is NOT fixed

**D2's reader half remains open** in `DEFECTS-001`. D10 closes the practical
path for mechanism ids arriving from `traverse`, but
`app/core/signal_adapters.py:182` also produces one from V4's
`causal_parent_id`, which never touches `mechanism_edge` at all.

The gate cannot resolve it by lookup either: `gates.py` and `reducer.py` are
PURE by Phase 0 rule 3, enforced by `tests/phase0/test_reducer_purity.py`, and
`reduce_company_impact` takes no session. So the approval state must arrive as
a field on the draft, set by an impure caller, with a policy knob in
`gates.yaml` saying what its absence means — the shape `required_verifier_status`
/ `unknown_verifier_status_passes` already uses. That is a design decision with
an upstream wiring cost, and it was deliberately not taken here.
