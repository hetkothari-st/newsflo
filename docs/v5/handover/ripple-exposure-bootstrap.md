# Handover — crude ripple-exposure bootstrap, vocabulary extension, ADR-001

Session: 2026-08-17 · Branch: `wt/ripple-exposure-bootstrap`
Model: Claude Opus 5 · Worked in the **shared integration tree** for most of
the session (see "What a fresh session would not learn from the repo").

---

## 1. What I was asked to do

Four requests, in sequence:

1. **Produce a coarse crude ripple-exposure CSV** — ~60 listed companies across
   nine ripple families, each with an input-cost share sourced from a filing.
   Hard rules: never estimate `share_of_base`; verbatim excerpt must pass
   string containment; `source_page` mandatory; no DB import; report thin
   families rather than filling them; a meaningful UNSOURCED file expected.
2. **Finalise the import** — extend the tag vocabulary, re-tag the
   intermediated logistics rows, reject HUL, rule on Blue Dart, import at
   ESTIMATED / grade D / capped below PRIMARY. Then write a §7.2 amendment
   form for an econometric exposure route, arguing both sides, without
   implementing it.
3. **Record the rejection as an ADR**, run the back-test that was the
   redirect's reopening condition, and answer the pass-through-curve question.
4. **Amend the redirect to REJECTED**, source `hedge_ratio` at FILED grade for
   the nine ledger companies, and stop.

---

## 2. What I completed

### Already on master (committed by the genericity session as `f2e9d902`)

| what | path |
|---|---|
| Acquisition → extraction → gate → CSV pipeline | `backend/scripts/ripple_bootstrap/` (acquire, index_pdfs, locate, peek, sweep, note_blocks, write_findings, build_csv, verify_csv, import_ledger, roster) |
| 52 annual reports + provenance | `data/filings/<isin>/source.json` (URL, UTC retrieval, sha256); PDFs and `pages.json.gz` gitignored, re-acquire with `acquire.py` |
| Sourced / unsourced exposure CSVs | `data/ripple_exposures.csv` (11 rows), `data/ripple_exposures_UNSOURCED.csv` (43 rows) |
| Vocabulary extension + migration | `backend/config/exposure_tags.yaml` (+`input:base_oil`, `input:bought_in_freight`, `input:intermediated_air_capacity`), `backend/alembic/versions/0016_v5_exposure_tag_vocabulary_resync.py` |
| Exposure-measurement grade cap (new, and it binds) | `config/materiality.yaml` `exposure_measurement_grade_cap`, `ExposureView.measurement`, `channels._build`, `engine.py`; tests `tests/phase2/test_exposure_measurement_grade_cap.py`, `tests/phase3/test_migration_0016.py` |
| 11 ledger rows | `company_exposure`, all `measurement = ESTIMATED`, `reviewed_by = 'ST269 (repo owner)'`, imported through `approve_proposal` only |

### Committed on this branch

| what | path |
|---|---|
| ADR-001, redirect amended to REJECTED | `docs/v5/decisions/ADR-001-econometric-exposure.md` |
| The §7.2 amendment (superseded, retained as the working argument) | `docs/v5/amendments/AMENDMENT-002-econometric-exposure.md` |
| Back-test record | `docs/v5/amendments/AMENDMENT-002-BACKTEST.md` |
| The curve answer, traced through the code | `docs/v5/CURVE_BOOTSTRAP.md` |
| hedge_ratio sourcing + gate | `backend/scripts/ripple_bootstrap/source_hedge_ratio.py` |
| hedge_ratio artefacts | `data/hedge_ratio_FILED.csv` (5 rows), `data/hedge_ratio_UNSOURCED.csv` (6), `data/hedge_ratio_proposals.json` |
| Back-test probe scripts | `backend/scripts/ripple_bootstrap/backtest/` |

### Headline results

* **Filings do not carry the raw-material breakup.** 52/52 reports acquired;
  usable input-cost share for **9 companies — 7 of them logistics**. Outside
  logistics: **2 of 45**. Schedule III requires one "Cost of materials
  consumed" line; the Schedule VI class-wise disclosure is gone. Written up as
  `DATA_GAPS/filing-disclosure-limits.md` §14.
* **Six of seven families are thin** (<3 sourced companies). Only logistics is
  not. Not backfilled.
* **hedge_ratio is the cheap link**: 5 of 11 rows at `FILED` 0.0, containment
  5/5, from the SEBI LODR Reg 34(3) commodity-hedging disclosure.
* **The econometric route is rejected in both forms**, the redirect on a
  back-test that failed on its own nominated case.

---

## 3. What I found that is NOT written down anywhere in the repo

Everything else I found is in the files above. These are not.

**(a) The CEAT hedging excerpt's page number disagrees with the existing
`company_modifier` rows.** The two rows already in `company_modifier` (written
by another session) cite *"AR p.116-117 (PDF page 60)"*. My containment check
passes on **PDF page 61** of the same file
(`AR_29958_CEATLTD_2025_2026_A_20312897_23072026115614.pdf`, sha256 in
`data/filings/INE482A01020/source.json`). One of the two citations is off by
one. Mine is machine-verified against the stored text layer; theirs may be
counting the printed page. **Worth reconciling before either is trusted as a
citation a reader will follow.**

**(b) The CEAT sentence contains a pypdf glyph split, and it defeated the
gate on first run.** The text layer reads *"T he Company does not have any
exposure hedged through commodity during FY 2025-26."* My excerpt with the
subject failed `EXCERPT_NOT_IN_DOCUMENT`; I trimmed to a true substring rather
than embed the artefact. **Any other excerpt taken from a CEAT sentence
starting a paragraph will hit this.** It is a general property of these PDFs,
not a one-off — the same split appears on "T otal", "F ollowing", "E xposure".

**(c) My 5 hedge_ratio windows predate `DATA_GAPS/modifier-staleness.md`
§17.3 and do not follow it.** I set `effective_to` to the strict fiscal-year
end because the owner's instruction was "the period the disclosure actually
covers, do not use NULL". Consequence, measured: **0 of the 5 rows would
resolve for a shock dated today** (2026-08-17 is past 31 March 2026). §17.3
proposes a defensible carry-forward window for exactly this. **If §17.3 is
adopted, all five windows in `data/hedge_ratio_proposals.json` must be
re-dated before import** — they are currently the strict reading, not the
proposed one.

**(d) The two CEAT modifier rows in the DB resolve only because they use
`effective_to = NULL`** — the convenience the owner forbade mid-session.
Closing that hole un-resolves them. That tension is real and is the practical
argument for §17.3.

**(e) `data/filings/` is a reusable corpus and nothing says so.** 52
text-indexed Indian annual reports with sha256 provenance, already searched
for materials notes, LODR commodity tables, hedging statements and BRSR
tables. Any future sourcing task (pass-through commentary, segment notes,
borrowings, forex) should start here rather than re-acquiring. The PDFs are
gitignored; `acquire.py` re-fetches them from the URLs in `source.json`.

**(f) The FRED daily Brent series is unreachable from this machine.**
`https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU` resets the
connection, repeatably, through both curl and requests, while other hosts on
the same machine work. The back-test used Yahoo `BZ=F` monthly closes instead.
A production implementation that assumes FRED works will fail here.

---

## 4. What I was about to do next

Nothing — the owner said stop. Had the session continued, in this order:

1. **Pull the Fuel Surcharge Mechanism's reset cadence out of Blue Dart's
   filing.** It is the single best filing-sourced pass-through lead found: a
   named, company-specific, `FILED`-grade recovery mechanism, and the cadence
   IS the curve shape. See `data/hedge_ratio_UNSOURCED.csv`, reason
   `PASS_THROUGH_NOT_HEDGE`, and `docs/v5/CURVE_BOOTSTRAP.md` §4.
2. **EBITDA rows for the remaining 8 companies** from the reports already on
   disk — removes `no_ebitda=True` from every abstention, ~10 minutes each.
3. **The second look at Mahindra Logistics and TCI Express**, whose LODR
   entries I could not resolve on the first pass.

---

## 5. Open questions I was waiting on

1. **Is there to be a reviewed write path for `company_modifier`, and who
   builds it?** This is defect D1. I stopped at the artefact rather than
   writing, on the owner's instruction. `data/hedge_ratio_proposals.json` is
   shaped for whatever that path turns out to be. Until it exists, the 5
   FILED rows are sourced and unusable.
2. **§17.3 carry-forward: adopt or not?** Determines whether my five windows
   get re-dated (see 3c).
3. **VRL's `FX_LIMB_ONLY` call — overrule me or not?** Its LODR entry answers
   only the FX limb but then says no disclosure is warranted under the SEBI
   *commodity* circular. I read that conservatively as not a statement about
   hedging diesel, which is 27.6% of its cost. The exact text is in the
   unsourced row so the call can be reversed on the evidence.
3. **Should the 11 exposure rows be re-dated or re-based when `FILED` rows
   eventually exist?** Every current row is `ESTIMATED`; the grade-D cap makes
   them SECONDARY-only, which is correct now and may not be later.

---

## 6. What a fresh session would not learn from the repo alone

* **I worked in the shared integration tree, not a worktree.** Most of this
  session predates `docs/v5/SESSION_PROTOCOL.md` (committed 14:49 today). Two
  coordination incidents involved me and both are instructive:
  * I ran `git checkout DATA_GAPS.md` to revert my own edit **without
    re-reading the file first**, while another session was mid-rewrite of it.
    It discarded an uncommitted file I did not own. Nothing was ultimately
    lost, by luck rather than care.
  * A parallel session overwrote my edit to
    `DATA_GAPS/proposed-spec-amendments.md` mid-file; I re-applied and
    verified. **That edit is still uncommitted in the integration tree** — see
    §7.
  Both are exactly what §1 of the protocol exists to prevent. Use a worktree.
* **I minted migration `0016` mid-flight**, which §2 of the protocol now
  forbids. It has since been recorded as APPLIED in
  `docs/v5/MIGRATION_CLAIMS.md`, credited to the genericity session. No
  action needed; noted so the ledger's history is legible.
* **Suite numbers I reported during this session came from the shared tree**
  and are therefore not reportable under §4. The last full run I observed was
  3963 passed / 10 skipped / 0 failed, but it was measured in a tree other
  sessions were editing. **Re-run in a worktree before trusting it.** I also
  saw `tests/test_offline_benchmark.py` fail 5 tests under random ordering and
  pass in isolation and under `-p no:randomly` — order-dependent pollution
  that is not mine and may still be there.
* **`pass_through_curve` is empty again.** The CEAT proof-of-life curves were
  written by another session and then deleted on the owner's instruction. The
  end-to-end numbers in ADR-001's postscript (−₹209cr at 0d decaying to zero
  at 90d) are a **measurement taken while they existed**, not current state.
* **The dev DB is the shared canonical copy** (`backend/newsflo.db`), and it
  now holds 11 exposure rows, 2 modifiers and 1 financials row that no
  migration creates. A fresh worktree will not have them — worktrees do not
  carry the DB.
* **`import_ledger.py` is idempotent** on `(company_id, exposure_tag,
  as_of_date)` and skips rather than duplicating. Safe to re-run.
* **The verbatim gate caught three real errors this session**, none of them
  hypothetical: a cp1252 mojibake `₹`, the CEAT glyph split, and a fabricated
  control excerpt. It is doing work; do not route around it.
