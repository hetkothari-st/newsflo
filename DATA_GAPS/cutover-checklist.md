# DATA GAPS — V5 SERVING CUTOVER CHECKLIST

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

---

## V5 SERVING CUTOVER CHECKLIST

**Do not serve the V5 canonical path until every item here is done.** These
are not gaps in the data — they are settings that are *correct while V5 is
parallel and unserved* and *wrong the moment it is not*. They are listed
separately from the gap sections precisely so that "the ledger is still
empty" cannot be used to postpone reading them.

The dangerous state is not "V5 off" or "V5 on". It is the **partial
rollout**: some drafts carrying a computed band and some not, in the same
feed, indistinguishable to the reader.

### 1. Flip the two fail-OPEN gate keys — `config/gates.yaml`

| Key | Deployed | Must become | Blocks |
|---|---|---|---|
| `primary.unknown_materiality_delta_passes` | `true` | `false` | a band-less draft clearing the 2.0% PRIMARY materiality floor |
| `primary.unknown_sector_proxy_passes` | `true` | `false` | a draft of unknown parameter provenance clearing the PRIMARY sector-proxy ban |

Both are `true` because nothing computes a band or a parameter provenance on
the V4-fed canonical path today. **Flipping them is not a one-line change.**
Measured on 2026-08-17 by flipping both and running
`tests/phase0 tests/phase1 tests/phase2`: **5 failures**, every one of them a
fixture that reaches PRIMARY without a sensitivity block.

```
tests/phase0/test_firewall.py::test_primary_prose_has_deletion_rate_zero_on_the_fixture_corpus
tests/phase0/test_single_truth.py::test_the_fixture_primary_company_reaches_primary
tests/phase1/test_staleness.py::test_a_stale_exposure_blocks_primary_in_the_gate
tests/phase2/test_evidence_grade_cap.py::test_a_signal_set_with_no_sensitivity_block_is_unaffected
tests/phase2/test_sign_consistency_gate.py::test_the_phase0_fixture_company_is_reduced_exactly_as_before
```

The fixture work — giving those fixtures a computed band, or accepting that
they now reach SECONDARY — must be done in the **same change**. Do not flip
the keys and delete the failing assertions: three of those five exist
precisely to prove a company reaches PRIMARY, and deleting them removes the
only evidence that the flip did not simply switch PRIMARY off.

*(The Phase 3 review recorded 7 failures for the same experiment. The number
above is what this session measured on the current tip; the branch gained
`tests/phase2/test_evidence_grade_cap.py` and other fixtures in between.
Re-measure before acting rather than trusting either figure.)*

The `secondary_ripple` twins of both keys may stay `true`: a ripple already
admits weaker evidence by design.

**Owner: V5 serving phase.**

### 2. Confirm the escape warning is silent

`app/core/gate_warnings.py` emits a structured `WARNING` on the
`newsflo.gate` logger for every PRIMARY publication that passed a rule only
because one of those escapes fired, carrying
`gate_unknown_escape_rules`, `gate_tier`, `event_id` and `company_id`. It is
the audible version of the hole in item 1.

**After item 1, this warning must never fire.** If it still does, a code path
is constructing an `ImpactDraft` without a band and something is publishing
it as PRIMARY. Wire the logger into whatever alerting exists before cutover,
not after.

### 3. Re-run the coverage harness against the REAL universe

Every recall and precision number recorded anywhere in this repo was measured
on `backend/tests/coverage/fixtures/synthetic_universe.json`. Before serving,
run `audit_shock` against the production database and record the real
numbers. Expect them to be bad; the point is that they will be *specific*.

### 4. Get the expected-ripple map signed off

`backend/tests/coverage/fixtures/expected_ripple_map.yaml` is headed
`PROPOSED-PENDING-OWNER-SIGN-OFF` with `signed_off_by: null`. Until a domain
expert signs it, every recall figure is relative to the implementer's guess
at what should have surfaced.

### 5. Wire the liquidity feed and close the liquidity gate — `config/gates.yaml`

| Key | Deployed | Must become |
|---|---|---|
| `primary.min_adv_inr` | `null` (rule never walked) | a real INR threshold |
| `primary.unknown_liquidity_passes` | `true` | `false` |

Both together, in one change, with an `adv_20d_inr` actually supplied to the
gate — see **§12**. Setting the threshold while leaving
`unknown_liquidity_passes: true` closes nothing: every company would arrive
with `adv_20d_inr = None` and pass on the unknown escape instead of on the
rule. Setting `unknown_liquidity_passes: false` without a feed rejects the
entire universe from PRIMARY.

This is the only cutover item whose prerequisite is **data acquisition rather
than a code change**, so it has the longest lead time of anything on this
list. **Owner: repo owner.**

### 6. Delete `ripple_layers._TAXONOMY_LABELS` — it dies at cutover

**LOG ONLY. Do not fix this before cutover.** Fixing it now means fixing it
twice.

There are two mechanism→section-label tables in this repo and they describe
the same thing:

| | where | keyed by | dialect | consumer |
|---|---|---|---|---|
| V4 | `app/market/ripple_layers.py::_TAXONOMY_LABELS` (~line 91) | mechanism id | persisted | the live serving path |
| V5 | `config/section_taxonomy.yaml::labels` | mechanism id | persisted (v5.1.0) | `app/output/sections.py`, unserved |

The V5 file already carries every label the V4 table does, in the same
dialect, plus the `unknown_label` fallback the V4 table lacks — V4 folds an
unrecognised mechanism into `OTHER_LABEL` (`"other verified mechanisms"`),
which collapses distinct mechanisms into one bucket. So the correct end state
is **not** "reconcile the two tables". It is: the V5 section engine becomes
the serving path, `app/market/ripple_layers.py` stops being a section
renderer, and `_TAXONOMY_LABELS` is deleted outright.

Doing that reconciliation *before* cutover would mean pointing V4 at the YAML,
proving that change safe against the live feed, and then deleting the whole
code path a few weeks later anyway.

**This is a known drift class in this repo, not a one-off.** Two artefacts
describing one concept, edited independently, with nothing asserting they
agree:

* the **node-id dialect** defect (consolidated in `d03f50f7`–`00323b0a`):
  `section_taxonomy.yaml` was keyed in the registry's dialect while the
  pipeline persisted `normalize_node_id`'s. Nine of the 42 mechanisms
  rendered as `UNCLASSIFIED MECHANISM (…)` and fragmented into singleton
  sections. Fixed by keying one file in the dialect the writer actually
  emits, and pinning both halves with a test.
* the **broad-event vocabulary** (consolidated 2026-08-17):
  `cascade.BROAD_EVENT_TYPES` (10) and `config.IMPACT_BROAD_EVENT_TYPES`
  (11) with a comment in `config.py` asserting they were "the same set".
  They had drifted by `geopolitics`. Fixed by one base set, one *named*
  delta (`IMPACT_BROAD_EXTRA_EVENT_TYPES`) and
  `tests/test_broad_event_types_single_source.py`.

`_TAXONOMY_LABELS` is the third instance and the only one where the right fix
is deletion rather than consolidation, because one of the two copies is
scheduled to disappear.

*At cutover:* delete `_TAXONOMY_LABELS` and `OTHER_LABEL`'s section-label
role from `app/market/ripple_layers.py`, and add a test asserting no module
under `app/` holds a mechanism→label mapping outside
`config/section_taxonomy.yaml` — the same shape as the broad-event test
above, so a fourth instance cannot be introduced silently.

**Owner: V5 serving phase.**
