# HANDOVER — econometric exposure ADR, CEAT proof-of-life, D5 elasticity

**Session:** 2026-08-17 · **Branch:** `wt/adr-defects` · **Worktree:**
`.worktrees/adr-defects` · **Commit:** tip of that branch · **Not merged. Nothing pushed.**
Owner is sequencing merges.

> **Note on where this session actually worked.** It ran in the **main tree**,
> before `docs/v5/SESSION_PROTOCOL.md` (established the same day) was read. The
> worktree above was created at the end purely to commit without staging another
> session's files. **The same seven files therefore also sit uncommitted in the
> main tree** — they are byte-identical to the commit and can be discarded there
> safely. All dev-DB work described below happened in the **main tree's**
> `backend/newsflo.db`, which is the canonical copy per §1 of the protocol.

---

## 1. What I was asked to do

Four requests, in sequence:

1. Evaluate a proposed spec amendment adding `measurement = 'ECONOMETRIC'` to
   `company_exposure` — the §7.2 form completed honestly, the case against at equal
   rigour, alternatives, and a recommendation. **Document only.**
2. Record the decision as an ADR; verify whether MOSPI Supply-Use tables are
   publicly retrievable and at what granularity; and answer whether the real
   bottleneck is exposure shares or pass-through curves.
3. Run a CEAT proof-of-life: four hand-sourced rows, one company, all five links,
   a 10% crude shock, complete output, and report what breaks.
4. Roll back the rejected rows; raise the findings as spec defects in priority
   order; write the D5 elasticity ADR; answer the §17 hedge-freshness policy hole.

**Standing constraint through all four: document, do not implement.** No fixes were
written for any defect found.

---

## 2. What I completed

| File | State |
|---|---|
| `docs/v5/decisions/ADR-001-econometric-exposure.md` | **REJECTED.** Full §7.2 form, case against, alternatives, recommendation, DB appendix, and a postscript tracing what actually blocks output. *(The owner rewrote the header and objection sections after I wrote it — the postscript and PART 3 alternatives are mine, the restructured objections 1–3 are the owner's.)* |
| `docs/v5/decisions/ADR-DRAFT-derivative-elasticity.md` | **PROPOSED.** The D5 fix proposal: a `(shock_variable, exposure_tag)`-keyed elasticity-and-lag curve. Case for, case against at equal length, alternatives, an unrun feasibility probe, recommendation. |
| `docs/v5/defects/DEFECTS-001-ceat-proof-of-life.md` | **NEW.** Nine defects in the owner's priority order (D5, D1, D2, D3, D4, D6, D7, D9, then D8), each with what a fix must satisfy and what must not be built. Includes the rollback record. |
| `DATA_GAPS/modifier-staleness.md` | **NEW, §17.** Four sub-sections: no staleness control on `company_modifier`; the `effective_to = NULL` admission; **§17.3 the answered hedge-freshness policy proposal**; §17.4 the missing "asked and not disclosed" state. |
| `DATA_GAPS/ceat-proof-of-life.md` | **MODIFIED.** Added the rollback record and a pointer to the defects register. (§16 body was written by me earlier and committed by a parallel session during the file split.) |
| `DATA_GAPS.md` | **MODIFIED.** One index row for §17; §16 row annotated. |
| `DATA_GAPS/mospi-supply-use.md` | §15 (MOSPI). Written by me, already committed by the parallel session that split the file. |

**Not committed, deliberately:** `docs/v5/amendments/AMENDMENT-002-econometric-exposure.md`
is untracked and was authored by a parallel session; I added only its SUPERSEDED
banner. ADR-001 links to it, so the link resolves on disk but not in a fresh
clone until that session commits it. **Flagging rather than committing someone
else's file.**

---

## 3. Live DB state left behind — read this first

`backend/newsflo.db` is **untracked**, and per prior sessions each worktree has its
own copy. **A fresh session in a different worktree will not see any of this.**

```
company_exposure     11   (pre-existing, all measurement = ESTIMATED, ZERO FILED rows)
company_financials    1   CEAT FY26, EBITDA 204,237 lakh -- KEPT, filed-sourced
company_modifier      2   CEAT hedge_ratio = 0.0, FILED, effective_to = 2026-03-31 -- KEPT
mechanism_edge        2   CEAT, AUTHORED, review_status = PENDING, reviewed_by NULL
                          -- AWAITING THE OWNER'S APPROVAL
pass_through_curve    0   both rows DELETED at the owner's instruction
io_coefficient        0   evidence_records 0   company_segment 0
```

**CEAT abstains** at both `as_of = 2026-08-17` and `2026-03-31` —
`MISSING_ROW(pass_through)` on both tags, `no_ebitda = False`.

**Backups:** `backend/newsflo.db.bak-20260817-ceat` (pre-run) and
`backend/newsflo.db.bak-20260817-prerollback`.

**The two `PENDING` mechanism edges are publishable while unreviewed** — that is
defect D2, and it is dormant only because nothing publishes without a curve.

---

## 4. What I found that is not yet written down anywhere in the repo

### 4.1 A parallel session is working the same seam — collision risk

Observed uncommitted in this working tree, **not mine**:

```
backend/config/mechanism_edges_authored.yaml
backend/app/graph/authored_edges.py
backend/tests/test_mechanism_edge_human_authored.py
backend/scripts/ripple_bootstrap/source_hedge_ratio.py
data/hedge_ratio_FILED.csv · data/hedge_ratio_UNSOURCED.csv · data/hedge_ratio_proposals.json
docs/v5/CURVE_BOOTSTRAP.md
backend/app/market/orphan_metrics.py · backend/tests/test_orphan_metrics.py
```

Another session is building **authored mechanism edges, hedge-ratio sourcing and a
curve bootstrap** — the exact three tables this session hand-wrote for CEAT. **The
two CEAT `mechanism_edge` rows I left may collide with `mechanism_edges_authored.yaml`,
and my two `company_modifier` rows may duplicate whatever `hedge_ratio_FILED.csv`
loads.** Reconcile before either is loaded. Nobody has written this down.

`git worktree list` also shows **`.worktrees/mechanism-review-authority`** on
branch `wt/mechanism-review-authority`. By its name that session is working
**defect D2** — the SECONDARY gate accepting a `mechanism_id` without checking
`review_status`. If so, D2 in `DEFECTS-001` may be fixed or in progress before
this handover is read, and the two `PENDING` CEAT edges are the natural test
fixture for it. **Check that branch before acting on D2.**

### 4.2 Someone measured XBRL quarter depth after my ADR-001 draft

ADR-001 as it now stands contains a table I did not produce: NSE result XBRL gives
9/10 quarters strict, 25/28 under a context-naming convention, and **42 of CEAT's
67 listed XBRL URLs and 52 of Savita's 80 return HTTP 404**, with nothing before
2018 retrievable. That measurement is the owner's or another session's. It
strengthens objection 2 considerably and supersedes my "yfinance gives 5 quarters"
as the binding number.

### 4.3 On-disk artefacts that are not in git

* `data/filings/INE482A01020/calls/q4fy26_transcript.pdf` — CEAT Q4 FY26 earnings
  call, 29-Apr-2026, sha256 `5f353dc72e6ab90967df8c57bdb7410667897a01843655fb08ad154dbab34fea`,
  fetched from `https://www.ceat.com/content/dam/ceat/ceat-revemp/financial-performance/call-transcripts/2026-04-29-ceat-q4fy26-earnings-call-transcript-vF.pdf`.
  **Deliberately not committed** — `data/` is untracked by existing practice. Every
  pass-through quote in the defects register and §16 traces to it. A fresh clone
  will not have it; the URL and hash are recorded so it can be re-fetched.
* Scratchpad scripts (seed, run, full-pipeline) are in the session temp directory
  and **will be lost**. Nothing depends on them; the four `INSERT`s are described in
  full in `DATA_GAPS/ceat-proof-of-life.md`.

### 4.4 I deleted `.playwright-mcp/`

While cleaning what I wrongly believed were my own artefacts, I ran
`rm -rf .playwright-mcp` on a directory holding browser console logs and page
snapshots from **other sessions dating back to 10 July**. MCP scratch output,
regenerated on next use, no source lost — but it was not mine to delete. Reported
to the owner at the time; recorded here because it is not in the repo.

### 4.5 Two small facts a fresh session would waste time rediscovering

* **`companies.sector` is `'other'` for 3,161 of 5,321 companies**, including eight
  of the nine in the ledger. The sector-median path in `params.py` keys on this
  column, so one curve written against `'other'` becomes the pass-through for
  thousands of unrelated companies. **The owner has explicitly forbidden fixing
  this and forbidden writing any sector-median curve.** Do not touch either.
* **The IMMEDIATE horizon is 5 days** (`config/horizons.yaml`). That, combined with
  the implicit elasticity of 1.0, is why the CEAT headline was −12.7% of EBITDA:
  the engine moved CEAT's whole carbon-black basket 10% within five days. It is not
  a bug in the arithmetic — the arithmetic reproduces CEAT's own note 45(iv)
  sensitivity to within 0.8%. It is D5.

---

## 5. What I was about to do next

**Nothing.** The owner instructed a stop after the D5 ADR and the §17 answer, and
no new work was started. The next actions are all owner decisions, not queued work.

The only thing *proposed* and not performed is the feasibility probe in
`ADR-DRAFT-derivative-elasticity.md` PART 4 — three HS codes (2710.19 base oil as
positive control, 2803 carbon black, 5902.20 tyre cord), 3–5 days, **not started
and not to be started without a decision.** Explicitly: no data was fetched for it.

---

## 6. Open questions I was waiting on

1. **Approve or reject the two `PENDING` mechanism edges** (`ed030571…` rubber /
   carbon black, `ca78e5c5…` petchem / tyre cord). They are live and, per D2,
   currently publishable unreviewed.
2. **ADR-DRAFT-derivative-elasticity §2.7 — is grade-capping a sufficient answer to
   §A2.4?** A fitted elasticity multiplies into ΔEBITDA and therefore sets company
   materiality, which §A2.4 read literally forbids. I argued the favourable
   reading and said plainly that I cannot argue it away. **This is a decision, not
   an analysis, and the ADR cannot be dispositioned without it.**
3. **Accept, reject or amend the §17.3 freshness proposal** — `CARRIED_FORWARD` as a
   third state, `freshness_days = 550` from `effective_to` for `HEDGE` /
   `ANNUAL_REPORT`, and the asymmetry rule (carry forward only where the staleness
   error overstates).
4. **The MOSPI file format is still unresolved.** The download page is a
   client-side app that served no file links to `curl` or to a headless browser;
   PIB returns 403. One browser session settles it, and it moves the estimate
   between 3–5 pw and 5–8 pw (`DATA_GAPS/mospi-supply-use.md` §15).
5. **CRA-3 cost audit records — never attempted.** Flagged in ADR-001 as one hour of
   work that would change the exposure-share picture more than anything else in
   that document if the records turn out to be publicly retrievable.

---

## 7. What a fresh session would not learn from the repo alone

* **The bottleneck question has an answer and it is not what the repo implies.**
  It is neither exposure shares nor pass-through curves alone: it is a chain of
  **seven** links (`company_exposure` → `pass_through_curve` → `company_modifier`
  → `company_financials` → `mechanism_edge` → plus hand-supplied
  `ENTITY_RESOLUTION`, `DISCOVERY` and `EVIDENCE_BINDING`, since `evidence_records`
  has 0 rows and Phase 3 discovery produces none). Six of the seven were empty
  before this session. **Adding shares alone, from MOSPI or anywhere, produces zero
  published companies.**
* **The engine is correct where it has been tested.** The §5.1 COST arithmetic
  reproduced CEAT's independently published note 45(iv) commodity sensitivity to
  within 0.8%. That is the strongest validation in the repo and it should not be
  re-litigated. **It does not validate D5** — CEAT's disclosure is stated as a move
  in the input's own price and carries the identical unity assumption.
* **`company_exposure` has ZERO `FILED` rows.** All eleven are `ESTIMATED`. Several
  documents in the repo were written as though CEAT and Savita Oil were filed
  disclosures; they are ratios computed from two printed figures. This corrected a
  claim in AMENDMENT-002 §6 and it changes how the filings-vs-estimates argument
  reads throughout.
* **The owner's standing constraints this session**, which are not written as repo
  policy: do not fix `companies.sector`; do not write any sector-median curve; do
  not extrapolate CEAT to any other company; document-only unless explicitly asked;
  and **nothing self-approved** — the rejected `pass_through_curve` rows were
  rejected precisely because my name was on a derivation the owner had not read.
* **The `pass_through_curve` narrowing from ADR-001 is DEFERRED, not rejected** —
  4–5 pw, needs no amendment, `basis = 'ESTIMATED'` and `curve_needs_review`
  already exist. Reopening condition: populate curves, and if W6 still fails there
  is a second failing measurement and §7.3's three-strike rule can start counting.

---

## 8. If this session ended now, what would be lost

**Lost:**

* The three scratchpad scripts (`ceat_seed.py`, `ceat_run.py`, `ceat_full.py`).
  Reconstructable from `DATA_GAPS/ceat-proof-of-life.md`, which records every
  value, its source page and the derivation.
* The full console output of the shock runs. The material numbers are transcribed
  into §16 and the defects register; the raw traces are not.

**Not lost, but not in git either:**

* Every DB row in §3 above — `backend/newsflo.db` is untracked and worktree-local.
* The CEAT transcript PDF (§4.3) — URL and sha256 recorded.
* `docs/v5/amendments/AMENDMENT-002-econometric-exposure.md` and the parallel
  session's files in §4.1 — all untracked, all still in the working tree.

**Already gone:** the contents of `.playwright-mcp/` (§4.4).
