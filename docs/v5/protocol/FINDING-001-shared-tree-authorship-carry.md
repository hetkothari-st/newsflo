# PROTOCOL FINDING 001 — a correctly-staged commit can still carry another session's work

**Raised:** 2026-08-17 · **Against:** `docs/v5/SESSION_PROTOCOL.md` §7
**Status:** OPEN — proposed amendment below, not applied.
**Severity:** authorship/provenance, not data loss. Nothing was lost. What was
damaged is the ability to answer "who wrote this line" from the repository.

---

## 1. The finding in one sentence

§7 ("explicit-path staging only") governs **which paths** enter a commit; it
says nothing about **what content is at those paths**, so a session in a
shared tree that follows §7 exactly will still commit whatever another session
wrote into a path it legitimately owns.

`git add <explicit-path>` stages the file **as it is on disk right now**, not
as this session last wrote it. In a shared tree those two are different
whenever anyone else touched the file in between.

---

## 2. Measured instances

Three sessions worked the shared main tree on 2026-08-17 before
`SESSION_PROTOCOL.md` (`ee302d11`, 14:49) was written, and each created its
worktree only at wrap-up, to commit. Every instance below is a session
following the staging rule correctly.

### 2.1 `ADR-001-econometric-exposure.md` — a four-way composite, committed twice

Blob `eebdcc83` is **byte-identical** in `8274b6b8` (adr-defects, 14:59:19)
and `b06362df` (ripple-exposure-bootstrap, 15:01:35). One file, 376 lines,
with at least four authors:

| region | content | authored by | committed by |
|---|---|---|---|
| Postscript (L329–376), PART 3 alternatives (L317–328) | what actually blocks output | adr-defects | both |
| Objections 1–3, restructured (L63–139) | the case against | the owner | both |
| Objection 2's XBRL depth table (L84–103) | 9/10 strict, 25/28 by convention, 42-of-67 and 52-of-80 HTTP 404 | owner or a third session — **adr-defects states it is not theirs** | both |
| `### The redirect — REJECTED` (L221–316, **96 lines**) | back-test ran, failed, status amended | **ripple-exposure-bootstrap** | **both** |

The answer to the specific question asked: **yes.** The redirect-REJECTED
amendment is in the blob, and `8274b6b8` — the adr-defects commit, made 2m16s
*before* the ripple commit — contains it. That content is the ripple session's
turn-4 deliverable ("Amend the redirect to REJECTED", ripple handover §1.4).

Corroborating evidence that the carry is real and not co-authorship: the
section committed in `8274b6b8` cites
`docs/v5/amendments/AMENDMENT-002-BACKTEST.md` as its evidence, and that file
**exists in no commit on that branch**. `8274b6b8` standing alone contains a
dangling reference to a file only the other session had.

### 2.2 `AMENDMENT-002-econometric-exposure.md` — the carry running the other way

`b06362df` (ripple) commits this file. Its 26-line `> ## SUPERSEDED` banner
(L3–28) was written by **adr-defects**, whose handover §2 states it plainly:
*"is untracked and was authored by a parallel session; I added only its
SUPERSEDED banner… Flagging rather than committing someone else's file."*

adr-defects made the right call on the file and still had its own text carried
into someone else's commit by the same mechanism, in the opposite direction.

*(Aside, not contamination: that banner still reads "the redirect… as
DEFERRED, not rejected", which ADR-001 in the same commit supersedes. Stale
cross-reference inside `b06362df`. Not mine to fix — flagged for the ADR's
owner.)*

### 2.3 `2ee521d2` — the same class, already on master

The DATA_GAPS per-topic split, committed by the coordination-setup session,
carried distinct work from **two** other sessions:

- adr-defects: `DATA_GAPS/ceat-proof-of-life.md` §16 body and
  `DATA_GAPS/mospi-supply-use.md` §15 (adr-defects handover §2).
- mechanism-review-authority: `DATA_GAPS/fertilizer-complex.md` §15 and
  `DATA_GAPS/cutover-checklist.md` item 6 (genericity handover, "already
  committed by the owner, not by me").

This one is **already merged**. It is the precedent, and it is why this is a
class rather than an incident.

**And it is the cleanest demonstration of the defect, because the audit that
checked it passed.** The DATA_GAPS split was verified lossless, and it *was*
lossless — every section that existed before the split existed after it. But
it was lossless **partly because it swept in four sections the authoring
sessions had not yet committed**. Had those sessions' edits not been sitting
in the shared tree at that moment, the split would have been lossless over a
strictly smaller corpus, and the audit would have passed identically.

The audit was correct. The mechanism it certified was wrong. A preservation
check answers *did content survive*; it cannot answer *did content arrive from
somewhere it should not have*. That is the same blind spot as `--stat`, at a
different layer: both compare **what is present**, and this class of defect
does not change what is present — it changes **who put it there**. A
contaminated commit and a clean one are indistinguishable to every
content-preserving check, which is why the only instrument that ever caught
any of this was four sessions writing down, in prose, what they believed they
had authored.

### 2.4 Clean by comparison

`wt/mechanism-review-authority` (`65e3f5d3`, `262bb6df`, `fbe609d5`,
`6150372b`) carries **no** other session's content. Every path in those four
commits is claimed by its own handover, and the two sessions that observed
those files uncommitted in the shared tree (adr-defects §4.1) explicitly
declined to stage them. Same shared tree, same window, no carry — so the
failure is not inevitable, which is what makes a rule worth writing.

---

## 3. Why §7 did not catch it, precisely

§7 prescribes two checks:

> verify `git diff --cached --stat` before commit and `git show --stat HEAD`
> after

Both are `--stat`. `--stat` reports **paths and line counts**. Every instance
above passes `--stat` review cleanly: the path is one the session owns, and
the line count is large because the session did in fact write a large document
there. `--stat` cannot represent authorship, so no amount of diligence at that
granularity would have surfaced any of this.

The rule is not being under-followed. The rule is measuring the wrong thing.

§7's own framing names its scope — "defense in depth" against **staging
sweeps**, where the wrong *path* enters the commit (`git add -A`, `git commit
-a`). That failure is loud: an unrelated file appears in `--stat`. This is the
quiet twin: the right path, the wrong content, and nothing in the output
differs from a correct commit.

---

## 4. Proposed fix

Not applied. Three parts; (a) and (b) are the amendment, (c) is optional.

### (a) Replace the `--stat` checks with a content check

Amend §7:

> **§7 Staging discipline (defense in depth)**
>
> Explicit-path staging only. Before committing, read `git diff --cached` **in
> full** — not `--stat`. `--stat` reports paths and line counts and **cannot
> show authorship**; a commit that carries another session's edits at a path
> you legitimately own passes every `--stat` check. Confirm each hunk is text
> this session wrote. After committing, `git show --stat HEAD`.
>
> Never stage: `.superpowers/`, `api_keys.txt`, `*.db`, another session's
> files. In the integration tree these rules are absolute.

### (b) Add the never-carry rule and its escape hatch

New §7.1:

> **§7.1 Never commit a hunk you did not write.**
>
> `git add <path>` stages the file **as it is on disk**, not as you last wrote
> it. In a shared tree those differ whenever another session touched the path
> in between, so owning a path is not evidence that you authored its current
> contents.
>
> If `git diff --cached` shows a hunk you did not type, do one of:
>
> 1. **Preferred** — leave it. Unstage the file (`git restore --staged
>    <path>`) and let its author commit it.
> 2. **When the file cannot be split** (one document, two authors, and the
>    other session has stopped), commit it and **record the carry** with a
>    trailer, so the log answers the question the diff cannot:
>
>    ```
>    Carried-From-Session: ripple-exposure-bootstrap docs/v5/decisions/ADR-001-econometric-exposure.md (### The redirect — REJECTED)
>    ```
>
> A carry that is recorded is a coordination note. A carry that is not is a
> false authorship claim that survives in the log forever, and only the
> handovers — which are not read by `git log`, `git blame`, or any reviewer —
> can correct it.

### (c) Optional mechanical backstop

A pre-commit hook comparing each staged path's on-disk mtime against a
session-local write log, refusing paths modified since this session last wrote
them. Correct, and heavier than the problem: §1 already prevents the whole
class, and after 2026-08-17 every session is in a worktree. Recommend
recording the idea and not building it until a fourth instance appears.

### (d) State plainly that §1 is the actual fix

§7 is a backstop for the residual case. The load-bearing rule is §1 —
**one worktree per session**. Every instance in §2 traces to three sessions
sharing one tree; none is reachable from separate worktrees, because there is
no shared path for the other session's bytes to arrive on. §8 already says
isolation is the primary defense; §7 should not read as though careful staging
were an alternative to it. It is not, and this finding is the measurement that
shows why.

---

## 5. Disposition of the two branches this was found in

Contamination is confined to **two documents** (§2.1, §2.2), both under
`docs/v5/`, both already reconciled in content — the ADR-001 blobs are
byte-identical, so the merge is clean and no reader sees a different document
depending on which branch landed first. No code, no test, no data file, and no
migration carries another session's work.

Recorded here rather than repaired: rewriting history on two branches to
re-attribute one document would cost more than it recovers, and the
attribution now exists in this file, which is the thing that was actually
missing.
