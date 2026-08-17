# Back-test probe — evidence behind ADR-001's redirect rejection

These two scripts produced the numbers in
`docs/v5/amendments/AMENDMENT-002-BACKTEST.md`, which is the evidence
ADR-001 rests on when it rejects the `pass_through_curve` redirect.

**They are a probe, not a component.** They write nothing, are wired into
nothing, and are committed only so the decisive input to a decision record is
reproducible. Do not import from them.

```
python backtest_run.py          # from this directory
```

## Prerequisites

* `backtest_probe.py` reads `brent_bzf.json` **from its own directory** — a
  cached Yahoo chart response, deliberately not committed. Regenerate:

  ```
  curl -s -A "Mozilla/5.0" \
    "https://query1.finance.yahoo.com/v8/finance/chart/BZ%3DF?range=25y&interval=1mo" \
    -o brent_bzf.json
  ```

  It uses Brent **futures** monthly closes, not daily spot. A production
  implementation should use FRED `DCOILBRENTEU` — which is unreachable from
  this machine (connection reset, repeatably, curl and requests both), which
  is why the probe does not.

* Quarterly P&L comes live from the NSE corporate-filings API. Expect roughly
  half the historical XBRL URLs to 404, and expect facts in the older files to
  reference a context id (`OneD`) the document never declares — see
  `parse_xbrl(..., allow_convention=True)` and the "STRICT vs RELAXED" split in
  the output. The relaxed mode reads those under an assumption about a naming
  convention. **Fine for a probe, never acceptable as ledger provenance.**

## The one thing to read before reusing any of this

`parse_xbrl` was originally written with a regex over `<xbrli:context>` and it
**silently dropped 16 of CEAT's 25 resolvable filings**. That would have been
reported as *missing data* — a false finding about the world caused by a
tooling limit — and CEAT's resulting levels R² of 0.33 came very close to
being reported as evidence the method worked. It is an `ElementTree` parse
now. Any acquisition path built from this needs a test that distinguishes
"the document does not contain it" from "we could not read it".
