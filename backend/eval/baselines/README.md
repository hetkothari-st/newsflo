# `eval/baselines/` — the no-regression baseline

**`main.json` is deliberately absent.**

Task 7.3 adds a no-regression rule on top of the absolute gates:

> no merge may reduce PRIMARY precision or ripple recall versus the current
> main branch baseline, even if absolute gates still pass.

That rule needs a stored measurement of `main` to compare against. There is
none, because **no corpus has ever been scored**: the Gate Zero labeled
corpus is empty (`DATA_GAPS.md` §1), so nobody knows this system's PRIMARY
precision or its ripple-family recall — not approximately, not at all.

So the evaluator **refuses** the comparison rather than passing it:

```
REFUSE no_regression: no stored baseline at main.json (…/eval/baselines/main.json),
        so the no-regression rule cannot be evaluated. It ships absent because no
        corpus has ever been scored (DATA_GAPS sections 1 and 11). Refused, not passed.
```

A refusal exits non-zero. A placeholder baseline — zeros, or plausible
numbers, or last week's guess — would exit zero and would make every future
merge look non-regressive against a measurement nobody made. That is the
fabrication this whole phase exists to prevent, and
`tests/phase7/test_shipping_gates.py::test_the_baseline_file_ships_absent`
fails the moment a file appears here.

## Writing the first real baseline

1. Label the corpus (`DATA_GAPS.md` §1 — human work, two independent
   labelers, `backend/tools/eval_ui.py`).
2. Run the harness against it and write its `gate_metrics()` out.
3. Save it here as `main.json`:

```json
{
  "commit": "<the sha of main when this was measured>",
  "measured_at": "<ISO date>",
  "corpus_events": 300,
  "metrics": {
    "primary_precision": 0.0,
    "ripple_family_recall": 0.0
  }
}
```

   The two metric values above are **placeholders in this example only** —
   write the numbers the harness produced, and delete this README's claim
   that no baseline exists when you do.
4. Update `tests/phase7/test_shipping_gates.py::test_the_baseline_file_ships_absent`
   and `DATA_GAPS.md` §11 in the same commit, so the repo never carries a
   baseline nobody can trace.

**Owner:** repo owner (the corpus is human work).
