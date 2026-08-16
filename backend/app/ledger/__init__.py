"""V5 PHASE 1 -- the company exposure ledger.

The durable asset (docs/v5/02_PHASE_1_exposure_ledger.md). This package is
MACHINERY ONLY: it builds, guards, reviews, ages and measures the ledger.
It contains no exposure data and produces none -- every table it touches
ships empty and is filled only by a human approving a proposal that carries
a verbatim excerpt from a filing.

  freshness.py  how old is too old, per exposure kind (config policy)
  review.py     THE ONLY WRITER of `company_exposure`
  staleness.py  the nightly STALE flag and the gate input it produces
  coverage.py   coverage rows, extractor quality, Prometheus-text metrics
  channels.py   the ledger -> signal join: no exposure row, no channel
  vocabulary.py the closed value sets the schema's text columns accept
"""
